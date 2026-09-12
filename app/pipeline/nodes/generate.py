# ============================================================
# [v1] 노드: generate — LLM 호출로 NPC 대사 생성
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (cache_write 직전)
# 구현(요약): 공용 LLMClient(세마포어+429 백오프 내장)로 prompt -> response
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ------------------------------------------------------------
# [v2] 운영 로그 — 프롬프트가 비었는지, 정제 후 대사가 사라졌는지 잡는다.
# 구현일: 2026-09-12 | 작성: kys (ops-logging/kys/v1)
# ============================================================
from app.core.logger import get_logger
from app.core.wording import clean_line
from app.llm.client import get_llm
from app.pipeline.state import DialogueState

logger = get_logger(__name__)

# 핫패스 공용 클라이언트 (세마포어/백오프는 LLMClient 내부에서 처리)
_llm = get_llm()


async def generate(state: DialogueState) -> dict:
    """[노드] 조립된 프롬프트로 LLM 호출 → NPC 대사 생성.

    동시성 제한·429 재시도는 LLMClient가 담당.
    담당: LLM 클라이언트 배선 = 정찬희 / 품질 가드·프롬프트 = 박준형.
    """
    prompt = state.get("prompt", "")
    if not prompt:
        # 프롬프트 조립이 실패한 것 — LLM은 아무 말이나 만들어내므로 여기서 드러내야 한다.
        logger.error("프롬프트가 비었는데 LLM 호출: node=%s stage=%s",
                     state.get("node_id"), state.get("stage"))
    response = await _llm.generate(prompt)
    # 마크업을 여기서 걷어낸다 — 이 값이 그대로 캐시에 굳고 앱 Text로 그려진다.
    cleaned = clean_line(response)
    if response and not cleaned:
        logger.warning("정제 후 대사가 사라짐 (원문 %d자): %s", len(response), response[:60])
    return {"response": cleaned}
