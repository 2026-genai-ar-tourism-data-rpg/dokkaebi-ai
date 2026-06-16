# ============================================================
# [v1] 노드: generate — LLM 호출로 NPC 대사 생성
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (cache_write 직전)
# 구현(요약): 공용 LLMClient(세마포어+429 백오프 내장)로 prompt -> response
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from app.llm.client import LLMClient
from app.pipeline.state import DialogueState

# 핫패스 공용 클라이언트 (세마포어/백오프는 LLMClient 내부에서 처리)
_llm = LLMClient()


async def generate(state: DialogueState) -> dict:
    """[노드] 조립된 프롬프트로 LLM 호출 → NPC 대사 생성.

    동시성 제한·429 재시도는 LLMClient가 담당.
    담당: LLM 클라이언트 배선 = 정찬희 / 품질 가드·프롬프트 = 박준형.
    """
    prompt = state.get("prompt", "")
    response = await _llm.generate(prompt)
    return {"response": response}
