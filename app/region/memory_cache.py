# ============================================================
# [v1] 지역 인메모리 캐시 (존 서버 패턴)
# pipeline: AI 백엔드 / 런타임 데이터 핫 계층 (아키텍처 1-2)
# 구현(요약): LRU로 동시 상주 지역 수 제한, 지역 워킹셋(노드 텍스트) RAM 적재/조회.
#            읽기 캐시(원천=DB). 미스 시 DB 리빌드는 TODO
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
# ============================================================
from collections import OrderedDict

from app.config import get_settings
from app.core.logger import get_logger

logger = get_logger(__name__)


class RegionMemoryCache:
    """지역 워킹셋 인메모리 캐시. 한 세션 locality를 활용해 RAM에서 직접 서빙.

    - LRU로 동시 상주 지역 수를 config.region_cache_max로 제한
    - 지역 안에서도 노드 수를 config.region_cache_nodes_max로 제한(LRU)
    - 휘발성/인스턴스별 → 어디까지나 읽기 캐시(소스 오브 트루스 = DB)
    """

    def __init__(self, max_regions: int, max_nodes_per_region: int) -> None:
        self._max = max_regions
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

    def get_text(self, node_id: str) -> str | None:
        """상주 중인 지역들에서 노드 텍스트 조회. 미스면 None. 히트한 노드는 LRU 갱신."""
        for nodes in self._regions.values():
            if node_id in nodes:
                nodes.move_to_end(node_id)     # 계속 쓰이는 노드는 evict 대상에서 밀어둔다
                return nodes[node_id]
        # TODO(정찬희): 미스 시 DB에서 해당 노드의 지역을 warm() 후 재조회
        return None


_cache: RegionMemoryCache | None = None


def get_region_cache() -> RegionMemoryCache:
    """지역 캐시 싱글톤(프로세스 RAM). 핫패스 공용."""
    global _cache
    if _cache is None:
        s = get_settings()
        _cache = RegionMemoryCache(s.region_cache_max, s.region_cache_nodes_max)
    return _cache
