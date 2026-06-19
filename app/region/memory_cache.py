# ============================================================
# [v1] 지역 인메모리 캐시 (존 서버 패턴)
# pipeline: AI 백엔드 / 런타임 데이터 핫 계층 (아키텍처 1-2)
# 구현(요약): LRU로 동시 상주 지역 수 제한, 지역 워킹셋(노드 텍스트) RAM 적재/조회.
#            읽기 캐시(원천=DB). 미스 시 DB 리빌드는 TODO
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from collections import OrderedDict

from app.config import get_settings
from app.core.logger import get_logger

logger = get_logger(__name__)


class RegionMemoryCache:
    """지역 워킹셋 인메모리 캐시. 한 세션 locality를 활용해 RAM에서 직접 서빙.

    - LRU로 동시 상주 지역 수를 config.region_cache_max로 제한
    - 휘발성/인스턴스별 → 어디까지나 읽기 캐시(소스 오브 트루스 = DB)
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

    def get_text(self, node_id: str) -> str | None:
        """상주 중인 지역들에서 노드 텍스트 조회. 미스면 None."""
        for nodes in self._regions.values():
            if node_id in nodes:
                return nodes[node_id]
        # TODO(정찬희): 미스 시 DB에서 해당 노드의 지역을 warm() 후 재조회
        return None


_cache: RegionMemoryCache | None = None


def get_region_cache() -> RegionMemoryCache:
    """지역 캐시 싱글톤(프로세스 RAM). 핫패스 공용."""
    global _cache
    if _cache is None:
        _cache = RegionMemoryCache(get_settings().region_cache_max)
    return _cache
