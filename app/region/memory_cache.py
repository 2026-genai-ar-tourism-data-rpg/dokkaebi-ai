# ============================================================
# [v1] 지역 인메모리 캐시 (존 서버 패턴)
# pipeline: AI 백엔드 / 런타임 데이터 핫 계층 (아키텍처 1-2)
# 구현(요약): LRU로 동시 상주 지역 수 제한, 지역 워킹셋(노드 텍스트) RAM 적재/조회.
#            읽기 캐시. 미스 시 TourAPI에서 그 노드만 직접 재조회(region 역인덱스인
#            DB가 없어 지역 전체 리빌드는 불가 — branching_service._grounding의
#            기존 단건 재조회 패턴을 흡수).
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ------------------------------------------------------------
# [v2] warm() 덮어쓰기 → 병합. 지역 워킹셋이 통째로 교체되던 버그 수정.
# 구현(요약): warm이 `self._regions[region] = nodes`로 **대입**이라, 같은 지역에 두 번째
#            warm이 오면 앞서 올려둔 노드 텍스트가 전부 사라졌다. 실제 영향:
#              · generator._apply_branching이 샛길 노드 1개로 본선 노드 전부를 지움
#              · 캐시가 프로세스 싱글톤이라 B의 시나리오 생성이 플레이 중인 A의 워킹셋을 교체
#                → context_load·branching_service가 grounding 미스 → 근거 없는 대사(환각)
#            병합으로 바꾸고, 무한 증식을 막으려 지역당 노드 수를 LRU로 상한
#            (config.region_cache_nodes_max). 빈 텍스트는 기존 값을 덮지 않는다.
# 구현일: 2026-08-12 | 작성: pjh (ai-logic-fix/pjh/v2)
# 수정일: 2026-08-11 | 캐시 미스 처리 구현: 정찬희
# ------------------------------------------------------------
# [v3] 미스 재조회가 지역 슬롯을 잠식하던 것 수정 + 재조회 대상 일반화.
# 구현(요약): _refetch가 `warm(node_id, {node_id: text})`로 저장해 **노드 id가 지역 키**가 됐다.
#            실측: 재조회 한 번에 REGION KEYS = ['종로', 'tour_1364932'].
#            상한이 region_cache_max(8)이라 미스 8번이면 진짜 지역 워킹셋이 LRU로 밀려나
#            플레이 중인 사용자의 grounding이 통째로 사라진다. 지역을 모르는 단건은
#            _ORPHAN 버킷 하나에 모아 지역 슬롯을 1개만 쓰게 한다.
#            또한 tour_ 접두만 재조회하던 것을 <출처>_<숫자 contentId> 규약으로 넓혔다 —
#            위시 앵커(wish_)·식음(food_)도 실제 contentId를 갖고 있어 원문이 나온다.
#            (그전엔 프로세스 재시작 뒤 그 노드들만 근거 없이 말했다)
# 구현일: 2026-08-19 | 작성: kys (dialogue-rework/kys/v1)
# ============================================================
from collections import OrderedDict

from app.config import get_settings
from app.core.logger import get_logger
from app.tourapi.client import TourAPIClient, TourAPIError

logger = get_logger(__name__)

_tour = TourAPIClient()

# 지역을 모른 채 단건 재조회한 노드가 들어가는 버킷. 지역 LRU 슬롯을 1개만 쓴다.
_ORPHAN = "_orphan"


class RegionMemoryCache:
    """지역 워킹셋 인메모리 캐시. 한 세션 locality를 활용해 RAM에서 직접 서빙.

    - LRU로 동시 상주 지역 수를 config.region_cache_max로 제한
    - 지역 안에서도 노드 수를 config.region_cache_nodes_max로 제한(LRU)
    - 휘발성/인스턴스별 → 어디까지나 읽기 캐시(소스 오브 트루스 = DB)
    - 휘발성/인스턴스별 → 어디까지나 읽기 캐시(소스 오브 트루스 = TourAPI)
    - 미스 시 TourAPI에서 그 노드 하나만 재조회해 캐시에 반영 후 반환
    """

    def __init__(
        self,
        max_regions: int,
        max_nodes_per_region: int | None = None,
    ) -> None:
        self._max = max_regions
        if max_nodes_per_region is None:
            max_nodes_per_region = get_settings().region_cache_nodes_max
        self._max_nodes = max(1, max_nodes_per_region)
        # region_id -> OrderedDict{node_id: text} (안쪽도 LRU)
        self._regions: "OrderedDict[str, OrderedDict[str, str]]" = OrderedDict()

    def warm(self, region_id: str, nodes: dict[str, str]) -> None:
        """지역 워킹셋(노드 텍스트)을 RAM에 **병합** 적재. LRU 초과 시 오래된 것부터 evict.

        대입이 아니라 병합인 이유: 같은 지역에 warm이 여러 번 온다(분기 노드 추가 워밍,
        동시 요청). 대입이면 나중 warm이 앞서 올려둔 노드를 전부 지워 grounding이 사라진다.
        빈 텍스트는 무시한다 — overview 조회에 한 번 실패했다고 이미 확보한 원문을 덮지 않도록.
        """
        working_set = self._regions.get(region_id)
        if working_set is None:
            working_set = OrderedDict()
            self._regions[region_id] = working_set

        for node_id, text in nodes.items():
            if not text:                       # overview 미확보 → 기존 값 보존
                continue
            working_set[node_id] = text
            working_set.move_to_end(node_id)

        while len(working_set) > self._max_nodes:
            evicted_node, _ = working_set.popitem(last=False)
            logger.info("지역 %s 노드 evict(LRU): %s", region_id, evicted_node)

        self._regions.move_to_end(region_id)
        while len(self._regions) > self._max:
            evicted, _ = self._regions.popitem(last=False)
            logger.info("지역 캐시 evict(LRU): %s", evicted)

    async def get_text(self, node_id: str, region_id: str = "") -> str | None:
        """노드 텍스트 조회. 미스면 TourAPI에서 재조회하고, 히트 시 LRU를 갱신.

        region_id를 알면 재조회 결과를 그 지역 워킹셋에 넣는다(모르면 고아 버킷).
        """
        for nodes in self._regions.values():
            if node_id in nodes:
                nodes.move_to_end(node_id)     # 계속 쓰이는 노드는 evict 대상에서 밀어둔다
                return nodes[node_id]
        return await self._refetch(node_id, region_id)

    async def _refetch(self, node_id: str, region_id: str = "") -> str | None:
        """캐시 미스 시 TourAPI 단건 재조회. 실패해도 그 노드만 grounding 없이 진행(전체는 안 막음)."""
        # node_id 규약: <출처>_<contentId>. tour_(관광)·wish_(위시 앵커)·food_(식음) 모두
        # 실제 contentId를 뒤에 달고 있어 detailCommon2로 원문을 받는다.
        # contentId가 숫자가 아니면 mock·합성 노드다(food_mock_0 등) → 조회하지 않는다.
        content_id = node_id.split("_", 1)[1] if "_" in node_id else ""
        if not content_id.isdigit():
            return None
        try:
            detail = await _tour.detail_common(content_id)
        except TourAPIError as e:
            logger.warning("캐시 미스 재조회 실패: %s (%s)", node_id, e)
            return None
        text = detail.get("overview") if detail else None
        if text:
            # 지역을 알면 그 워킹셋에, 모르면 고아 버킷 하나로.
            # (노드 id를 지역 키로 쓰면 미스 몇 번에 진짜 지역이 evict된다 — v3)
            self.warm(region_id or _ORPHAN, {node_id: text})
        return text


_cache: RegionMemoryCache | None = None


def get_region_cache() -> RegionMemoryCache:
    """지역 캐시 싱글톤(프로세스 RAM). 핫패스 공용."""
    global _cache
    if _cache is None:
        s = get_settings()
        _cache = RegionMemoryCache(s.region_cache_max, s.region_cache_nodes_max)
    return _cache
