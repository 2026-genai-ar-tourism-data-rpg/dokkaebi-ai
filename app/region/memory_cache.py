# ============================================================
# [v1] 지역 인메모리 캐시 (존 서버 패턴)
# pipeline: AI 백엔드 / 런타임 데이터 핫 계층 (아키텍처 1-2)
# 구현(요약): LRU로 동시 상주 지역 수 제한, 지역 워킹셋(노드 텍스트) RAM 적재/조회.
#            읽기 캐시. 미스 시 TourAPI에서 그 노드만 직접 재조회(region 역인덱스인
#            DB가 없어 지역 전체 리빌드는 불가 — branching_service._grounding의
#            기존 단건 재조회 패턴을 흡수).
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# 수정일: 2026-08-11 | 캐시 미스 처리 구현: 정찬희
# ============================================================
from collections import OrderedDict

from app.config import get_settings
from app.core.logger import get_logger
from app.tourapi.client import TourAPIClient, TourAPIError

logger = get_logger(__name__)

_tour = TourAPIClient()


class RegionMemoryCache:
    """지역 워킹셋 인메모리 캐시. 한 세션 locality를 활용해 RAM에서 직접 서빙.

    - LRU로 동시 상주 지역 수를 config.region_cache_max로 제한
    - 휘발성/인스턴스별 → 어디까지나 읽기 캐시(소스 오브 트루스 = TourAPI)
    - 미스 시 TourAPI에서 그 노드 하나만 재조회해 캐시에 반영 후 반환
    """

    def __init__(self, max_regions: int) -> None:
        self._max = max_regions
        # region_id -> {node_id: text}
        self._regions: "OrderedDict[str, dict[str, str]]" = OrderedDict()

    def warm(self, region_id: str, nodes: dict[str, str]) -> None:
        """지역 진입 시 워킹셋(노드 텍스트)을 RAM에 적재. LRU 초과 시 가장 오래된 지역 evict."""
        self._regions[region_id] = nodes
        self._regions.move_to_end(region_id)
        while len(self._regions) > self._max:
            evicted, _ = self._regions.popitem(last=False)
            logger.info("지역 캐시 evict(LRU): %s", evicted)

    async def get_text(self, node_id: str) -> str | None:
        """상주 중인 지역들에서 노드 텍스트 조회. 미스면 TourAPI에서 그 노드만 재조회."""
        for nodes in self._regions.values():
            if node_id in nodes:
                return nodes[node_id]
        return await self._refetch(node_id)

    async def _refetch(self, node_id: str) -> str | None:
        """캐시 미스 시 TourAPI 단건 재조회. 실패해도 그 노드만 grounding 없이 진행(전체는 안 막음)."""
        if not node_id.startswith("tour_"):
            return None  # 위시/식음 합성 노드 등 TourAPI 원본이 없는 ID
        try:
            detail = await _tour.detail_common(node_id.split("_", 1)[1])
        except TourAPIError as e:
            logger.warning("캐시 미스 재조회 실패: %s (%s)", node_id, e)
            return None
        text = detail.get("overview") if detail else None
        if text:
            self.warm(node_id, {node_id: text})  # 단건도 자기 자신을 region 키로 삼아 LRU 편입
        return text


_cache: RegionMemoryCache | None = None


def get_region_cache() -> RegionMemoryCache:
    """지역 캐시 싱글톤(프로세스 RAM). 핫패스 공용."""
    global _cache
    if _cache is None:
        _cache = RegionMemoryCache(get_settings().region_cache_max)
    return _cache
