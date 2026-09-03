# ============================================================
# [v1] 노드: retrieve — (옵션 RAG) 지역 인메모리 의미검색
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (use_rag=True 일 때만)
# 구현(요약): 쿼리 임베딩(EmbeddingClient) → 지역 인덱스 코사인 top-k(RegionSemanticIndex)
#            → 키워드overlap 재랭킹 → 저신뢰 시 LLM 쿼리 재작성 1회 재검색.
# 구현일: 2026-06-10 (의미검색 배선: 2026-06-16) | 작성: kys (semantic-search/kys/v1)
# 수정일: 2026-08-12 | 재랭킹·쿼리 변환·저신뢰 재검색 구현: 정찬희
# ============================================================
import asyncio
import re

from app.config import get_settings
from app.core.exceptions import LLMCallError
from app.core.logger import get_logger
from app.embeddings.client import EmbeddingClient
from app.llm.client import get_llm
from app.pipeline.state import DialogueState
from app.region.memory_cache import get_region_cache
from app.region.semantic_index import get_region_index

logger = get_logger(__name__)

# 핫패스 공용 클라이언트 (세마포어/백오프는 각 클라이언트 내부에서 처리)
_embed = EmbeddingClient()
_llm = get_llm()

_WORD_RE = re.compile(r"[\w가-힣]+")


def _tokenize(text: str) -> set[str]:
    """공백 기반 형태소 분석기가 없어 쓰는 최소 휴리스틱: 2자 이상 단어의 소문자 집합."""
    return {w.lower() for w in _WORD_RE.findall(text) if len(w) > 1}


def _lexical_overlap(query: str, text: str) -> float:
    """query 토큰이 text에 얼마나 겹치는지(0~1). 크로스인코더 없이 쓰는 경량 재랭킹 신호."""
    q_tokens = _tokenize(query)
    if not q_tokens:
        return 0.0
    return len(q_tokens & _tokenize(text)) / len(q_tokens)


async def _search_and_rerank(query: str, region_id: str, s) -> tuple[list[tuple[str, str, float]], float]:
    """임베딩 → 코사인 top-k(인덱스 적재=이지선) → 텍스트 조회 + 키워드overlap 블렌드 재랭킹.

    반환: ([(node_id, text_or_id, blended_score)] 점수 내림차순, top 신뢰도).
    """
    query_vec = await _embed.embed_one(query)
    index = get_region_index(region_id)
    hits = index.search(query_vec, top_k=s.search_top_k, min_score=s.search_min_score)
    if not hits:
        return [], 0.0

    cache = get_region_cache()
    texts = await asyncio.gather(*[cache.get_text(node_id) for node_id, _ in hits])
    w = s.search_rerank_lexical_weight
    reranked = [
        (node_id, text or node_id, cos * (1 - w) + _lexical_overlap(query, text or "") * w)
        for (node_id, cos), text in zip(hits, texts)
    ]
    reranked.sort(key=lambda r: r[2], reverse=True)
    return reranked, reranked[0][2]


async def _rewrite_query(query: str) -> str | None:
    """저신뢰 시 검색어를 관광지 grounding 검색에 맞게 1회 재작성. 실패하면 재검색 스킵(None)."""
    prompt = (
        "다음 사용자 발화를 관광지 설명 검색에 적합한 핵심 검색어로 한 줄 재작성해라. "
        "설명·따옴표·군더더기 없이 검색어만 출력.\n"
        f"발화: {query}"
    )
    try:
        rewritten = await _llm.generate(prompt, temperature=0.0, max_tokens=60)
    except LLMCallError as e:
        logger.warning("쿼리 재작성 실패, 원 쿼리 결과 유지: %s", e)
        return None
    rewritten = rewritten.strip().strip('"').strip("'")
    return rewritten or None


async def retrieve(state: DialogueState) -> dict:
    """[노드][옵션] 대형 텍스트/교차검색 시 지역 인메모리 임베딩 검색(기획 11-10).

    배선: 쿼리 → 임베딩 → 지역 인덱스 코사인 top-k → 키워드overlap 재랭킹 → 청크/신뢰도.
    신뢰도가 search_low_confidence_threshold 미만이면 LLM으로 쿼리 재작성 후 1회 재검색해
    더 나은 쪽을 채택(재작성 실패·개선 없으면 원래 결과 유지).
    담당: 박준형(검색 알고리즘·top-k·재랭킹·신뢰도 평가·저신뢰 시 재검색).
    """
    s = get_settings()
    # 검색 쿼리: 명시 query 우선, 없으면 그 장소 컨텍스트로 폴백
    query = state.get("query") or state.get("context") or ""
    region_id = state.get("region_id", "")
    if not query:
        return {"retrieved": [], "confidence": 0.0}

    results, confidence = await _search_and_rerank(query, region_id, s)

    if confidence < s.search_low_confidence_threshold:
        rewritten = await _rewrite_query(query)
        if rewritten and rewritten != query:
            retry_results, retry_confidence = await _search_and_rerank(rewritten, region_id, s)
            if retry_confidence > confidence:
                results, confidence = retry_results, retry_confidence

    chunks = [text for _, text, _ in results]
    return {"retrieved": chunks, "confidence": confidence}
