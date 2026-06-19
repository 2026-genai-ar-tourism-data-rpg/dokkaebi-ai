# ============================================================
# [v1] 지역 의미검색 인덱스 — 인메모리 numpy 코사인 (Tier 1)
# pipeline: AI 백엔드 / 런타임 핫 계층 (아키텍처 1-2 · 기획 11-10 의미검색)
# 구현(요약): 지역별 노드 임베딩 행렬을 RAM에 적재(add) → 쿼리 벡터로 brute-force
#            코사인 top-k(search). Vector DB/ANN 없음(지역당 수십~수천 벡터면 numpy로 충분).
#            인덱싱(add)=이지선 / top-k·재랭킹·임계 튜닝=박준형.
# 구현일: 2026-06-16 | 작성: kys (semantic-search/kys/v1)
# ============================================================
from collections import OrderedDict

import numpy as np

from app.config import get_settings
from app.core.logger import get_logger

logger = get_logger(__name__)


class RegionSemanticIndex:
    """한 지역의 노드 임베딩 인메모리 인덱스. brute-force 코사인 top-k.

    - add   : 빌드타임/지역 워밍 시 노드 벡터 적재 (정규화해 보관) — 이지선
    - search: 쿼리 벡터로 top-k 노드 반환 — 박준형(재랭킹·쿼리변환·저신뢰 재검색은 TODO)
    """

    def __init__(self, region_id: str, dim: int) -> None:
        self._region_id = region_id
        self._dim = dim
        self._ids: list[str] = []                 # 행 i ↔ node_id
        self._matrix = np.zeros((0, dim), dtype=np.float32)  # (N, dim) L2 정규화 보관

    def add(self, node_ids: list[str], vectors: list[list[float]]) -> None:
        """노드 임베딩을 인덱스에 적재(정규화해 누적). 담당: 이지선(빌드타임 인덱싱).

        node_ids[i] ↔ vectors[i]. 코사인 = 정규화 후 내적이므로 보관 시 L2 정규화.
        """
        if not node_ids:
            return
        mat = np.asarray(vectors, dtype=np.float32)
        if mat.shape[1] != self._dim:
            raise ValueError(f"임베딩 차원 불일치: {mat.shape[1]} != {self._dim}")
        mat = _l2_normalize(mat)
        self._ids.extend(node_ids)
        self._matrix = np.vstack([self._matrix, mat]) if self._matrix.size else mat
        logger.info("지역 의미검색 인덱스 적재: %s (+%d, 총 %d)",
                    self._region_id, len(node_ids), len(self._ids))

    def search(
        self, query_vec: list[float], top_k: int, min_score: float
    ) -> list[tuple[str, float]]:
        """쿼리 벡터로 brute-force 코사인 top-k. 담당: 박준형.

        반환: [(node_id, score)] score 내림차순, min_score 미만 컷.
        """
        if not self._ids:
            return []
        q = _l2_normalize(np.asarray([query_vec], dtype=np.float32))[0]
        scores = self._matrix @ q                      # (N,) 코사인 유사도
        k = min(top_k, len(self._ids))
        top_idx = np.argpartition(-scores, k - 1)[:k]  # 상위 k개(비정렬)
        top_idx = top_idx[np.argsort(-scores[top_idx])]  # 점수 내림차순 정렬
        results = [(self._ids[i], float(scores[i])) for i in top_idx if scores[i] >= min_score]
        # TODO(박준형): 재랭킹(크로스인코더 등)·쿼리 변환·저신뢰(<임계) 시 재검색
        return results

    def __len__(self) -> int:
        return len(self._ids)


def _l2_normalize(mat: np.ndarray) -> np.ndarray:
    """행별 L2 정규화(0 벡터는 그대로). 코사인을 내적으로 계산하기 위함."""
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return mat / norms


# --- 지역 인덱스 매니저 (지역 캐시와 동일한 LRU 패턴) ---
_indexes: "OrderedDict[str, RegionSemanticIndex]" = OrderedDict()


def get_region_index(region_id: str) -> RegionSemanticIndex:
    """지역 의미검색 인덱스 싱글톤(프로세스 RAM). 없으면 빈 인덱스 생성.

    LRU로 동시 상주 지역 수를 config.region_cache_max로 제한(지역 캐시와 동일 정책).
    빌드타임/워밍 시 add()로 채우고, retrieve 노드가 search()로 조회.
    """
    s = get_settings()
    if region_id in _indexes:
        _indexes.move_to_end(region_id)
        return _indexes[region_id]
    idx = RegionSemanticIndex(region_id, s.embed_dim)
    _indexes[region_id] = idx
    while len(_indexes) > s.region_cache_max:
        evicted, _ = _indexes.popitem(last=False)
        logger.info("지역 인덱스 evict(LRU): %s", evicted)
    return idx
