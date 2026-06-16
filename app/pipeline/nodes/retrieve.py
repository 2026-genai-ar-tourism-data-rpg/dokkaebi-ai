# ============================================================
# [v1] 노드: retrieve — (옵션 RAG) 지역 인메모리 의미검색
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (use_rag=True 일 때만)
# 구현(요약): 쿼리 임베딩(EmbeddingClient) → 지역 인덱스 코사인 top-k(RegionSemanticIndex)
#            배선까지 완료. top-k·재랭킹·신뢰도·저신뢰 재검색 알고리즘은 TODO(박준형).
# 구현일: 2026-06-10 (의미검색 배선: 2026-06-16) | 작성: kys (semantic-search/kys/v1)
# ============================================================
from app.config import get_settings
from app.embeddings.client import EmbeddingClient
from app.pipeline.state import DialogueState
from app.region.memory_cache import get_region_cache
from app.region.semantic_index import get_region_index

# 핫패스 공용 임베딩 클라이언트 (세마포어/백오프는 EmbeddingClient 내부에서 처리)
_embed = EmbeddingClient()


async def retrieve(state: DialogueState) -> dict:
    """[노드][옵션] 대형 텍스트/교차검색 시 지역 인메모리 임베딩 검색(기획 11-10).

    배선: 쿼리 → 임베딩 → 지역 인덱스 코사인 top-k → 청크/신뢰도.
    담당: 박준형(검색 알고리즘·top-k·재랭킹·신뢰도 평가·저신뢰 시 재검색).
    """
    s = get_settings()
    # 검색 쿼리: 명시 query 우선, 없으면 그 장소 컨텍스트로 폴백
    query = state.get("query") or state.get("context") or ""
    region_id = state.get("region_id", "")
    if not query:
        return {"retrieved": [], "confidence": 0.0}

    # 1) 쿼리 임베딩 (단건)
    query_vec = await _embed.embed_one(query)

    # 2) 지역 인덱스에서 코사인 top-k (인덱스 적재=이지선 / 알고리즘=박준형)
    index = get_region_index(region_id)
    hits = index.search(query_vec, top_k=s.search_top_k, min_score=s.search_min_score)

    # 3) 히트 노드 → 주입할 청크 텍스트로 변환(지역 RAM 캐시에서)
    cache = get_region_cache()
    chunks = [cache.get_text(node_id) or node_id for node_id, _ in hits]
    confidence = hits[0][1] if hits else 0.0

    # TODO(박준형): 재랭킹·쿼리 변환·confidence < 임계 시 재검색 루프
    return {"retrieved": chunks, "confidence": confidence}
