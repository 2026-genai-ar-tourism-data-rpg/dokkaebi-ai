# ============================================================
# [v1] 노드: prompt_assemble — 최종 프롬프트 조립
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (generate 직전)
# 구현(요약): persona + context(또는 RAG 청크) + stage 결합한 기본 골격. 템플릿 정교화 TODO(박준형)
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from app.pipeline.state import DialogueState


async def prompt_assemble(state: DialogueState) -> dict:
    """[노드] persona·context(또는 RAG 청크)·stage를 합쳐 최종 프롬프트 생성.

    담당: 박준형(프롬프트 설계 — npc_dialogue_v1 템플릿, '근거 외 발화 금지' 가드).
    """
    persona = state.get("persona", {})
    context = state.get("context", "")
    retrieved = state.get("retrieved", [])
    grounding = context or "\n".join(retrieved)
    # TODO(박준형): 기획 13-B npc_dialogue_v1 템플릿으로 교체 (말투·단계·가드 포함)
    prompt = (
        f"[persona] {persona}\n"
        f"[stage] {state.get('stage', '등장')}\n"
        f"[장소 정보] {grounding}\n"
        f"규칙: 위 장소 정보에 근거해서만, 도깨비 말투로 2~4문장."
    )
    return {"prompt": prompt}
