# ============================================================
# [v1] 노드: cache_read / cache_write — 대사 캐시
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (캐시 조회·저장)
# 구현(요약): 공통 캐시(core.cache: memory/redis)로 cache_key↔response 저장·조회.
#            히트 시 LLM 스킵(그래프가 END 분기). TTL=config.cache_ttl_s.
# 구현일: 2026-06-10 (캐시 배선: 2026-06-18) | 작성: kys
# ------------------------------------------------------------
# [v2] 운영 로그 — 히트/미스와 캐시 키를 남긴다.
# 구현(요약): "어제 고친 대사가 왜 그대로 나오지"의 답은 대개 캐시 히트인데,
#            로그가 없어 확인할 방법이 없었다. 키를 같이 찍어 무엇이 굳었는지 본다.
#            ⚠️ 빈 키는 결함이 아니다 — persona_inject가 자유 발화·QA 재작성일 때
#            일부러 캐시를 끈다(매번 다른 답이 나와야 하므로). 이걸 경고로 찍으면
#            정상 대화마다 거짓 경보가 떠서 진짜 경고가 묻힌다.
# 구현일: 2026-09-12 | 작성: kys (ops-logging/kys/v1)
# ============================================================
from app.config import get_settings
from app.core.cache import get_cache
from app.core.logger import get_logger
from app.pipeline.state import DialogueState

logger = get_logger(__name__)


async def cache_read(state: DialogueState) -> dict:
    """[노드] 대사 캐시 조회. 히트 시 cache_hit=True + response 반환(LLM 스킵)."""
    key = state.get("cache_key", "")
    if not key:
        # 의도된 캐시 우회 — 자유 발화(query)나 QA 재작성(qa_feedback)이 있을 때.
        logger.info("대사 캐시 우회(자유 발화/재작성) → LLM 생성")
        return {"cache_hit": False}
    cached = await get_cache().get(key)
    if cached is not None:
        logger.info("대사 캐시 HIT: %s (%d자)", key, len(cached))
        return {"cache_hit": True, "response": cached}
    logger.info("대사 캐시 MISS: %s → LLM 생성", key)
    return {"cache_hit": False}


async def cache_write(state: DialogueState) -> dict:
    """[노드] 생성된 대사를 캐시에 저장(다음 방문자 LLM 호출 0). TTL 적용."""
    key = state.get("cache_key", "")
    response = state.get("response", "")
    if key and response:
        ttl = get_settings().cache_ttl_s
        await get_cache().set(key, response, ttl)
        logger.info("대사 캐시 저장: %s (%d자, TTL %ds)", key, len(response), ttl)
    elif key and not response:
        # 키는 있는데 대사가 비었다 — 이건 진짜 이상. 다음 요청도 LLM을 또 탄다.
        logger.warning("대사가 비어 캐시 저장 못 함: %s", key)
    # 키가 없는 경우는 cache_read에서 이미 '우회'로 찍었다 — 여기서 또 찍지 않는다.
    return {}
