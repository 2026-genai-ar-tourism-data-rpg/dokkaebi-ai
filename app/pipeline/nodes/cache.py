# ============================================================
# [v1] 노드: cache_read / cache_write — 대사 캐시(Redis)
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (캐시 조회·저장)
# 구현(요약): 시그니처 + 기본값 반환. Redis 연동은 TODO(정찬희)
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from app.pipeline.state import DialogueState


async def cache_read(state: DialogueState) -> dict:
    """[노드] 대사 캐시 조회. 히트 시 cache_hit=True + response 반환(LLM 스킵).

    담당: 정찬희(Redis 캐시).
    """
    # TODO(정찬희): Redis에서 state["cache_key"] 조회 → 히트 시 response 채움
    return {"cache_hit": False}


async def cache_write(state: DialogueState) -> dict:
    """[노드] 생성된 대사를 캐시에 저장(다음 방문자 LLM 호출 0).

    담당: 정찬희(Redis 캐시).
    """
    # TODO(정찬희): state["cache_key"] -> state["response"] 저장(TTL 적용)
    return {}
