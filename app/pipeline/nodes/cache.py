# ============================================================
# [v1] 노드: cache_read / cache_write — 대사 캐시
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (캐시 조회·저장)
# 구현(요약): 공통 캐시(core.cache: memory/redis)로 cache_key↔response 저장·조회.
#            히트 시 LLM 스킵(그래프가 END 분기). TTL=config.cache_ttl_s.
# 구현일: 2026-06-10 (캐시 배선: 2026-06-18) | 작성: kys
# ============================================================
from app.config import get_settings
from app.core.cache import get_cache
from app.pipeline.state import DialogueState


async def cache_read(state: DialogueState) -> dict:
    """[노드] 대사 캐시 조회. 히트 시 cache_hit=True + response 반환(LLM 스킵)."""
    cached = await get_cache().get(state.get("cache_key", ""))
    if cached is not None:
        return {"cache_hit": True, "response": cached}
    return {"cache_hit": False}


async def cache_write(state: DialogueState) -> dict:
    """[노드] 생성된 대사를 캐시에 저장(다음 방문자 LLM 호출 0). TTL 적용."""
    key = state.get("cache_key", "")
    response = state.get("response", "")
    if key and response:
        await get_cache().set(key, response, get_settings().cache_ttl_s)
    return {}
