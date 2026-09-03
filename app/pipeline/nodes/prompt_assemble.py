# ============================================================
# [v1] 노드: prompt_assemble — 최종 프롬프트 조립
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (generate 직전)
# 구현(요약): npc_dialogue_v1 템플릿(기획_통합.md §13-B)으로 persona·grounding·상태 조립.
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# 수정일: 2026-08-12 | npc_dialogue_v1 템플릿 적용: 정찬희
# ------------------------------------------------------------
# [v2] 진행상황을 dict 그대로 넣던 것 → 사람 말로. (core.wording 공용)
# 구현(요약): `- 사용자 진행상황: {}` 처럼 파이썬 dict가 그대로 프롬프트에 들어가
#            내부 키·id가 대사로 샐 수 있었다. 분기 대화와 같은 변환기를 쓴다.
# 구현일: 2026-08-19 | 작성: kys (dialogue-rework/kys/v1)
# ============================================================
from app.core.wording import progress_line
from app.pipeline.state import DialogueState


async def prompt_assemble(state: DialogueState) -> dict:
    """[노드] persona·context(또는 RAG 청크)·stage를 합쳐 최종 프롬프트 생성.

    템플릿 = 기획_통합.md §13-B `npc_dialogue_v1`. 담당: 박준형(프롬프트 설계).
    """
    persona = state.get("persona", {})
    context = state.get("context", "")
    retrieved = state.get("retrieved", [])
    grounding = context or "\n".join(retrieved)
    place_name = state.get("node_name") or state.get("node_id", "")

    prompt = (
        f"[시스템]\n"
        f"너는 '{place_name}'을(를) 수호하는 도깨비 NPC '{persona.get('name', '이름 없는 도깨비')}'다.\n"
        f"- 모티프: {persona.get('motif', '')}  - 아키타입: {persona.get('archetype', '')}"
        f"  - 성격/말투: {persona.get('persona', '')}\n\n"
        f"[장소 실제 정보 — RAG 주입]\n"
        f"{grounding}\n\n"
        f"[규칙]\n"
        f"- 위 '장소 실제 정보'에 근거해서만 역사·문화를 말한다. 정보에 없으면 지어내지 않는다.\n"
        f"- 추리 유도가 아니라 '장소 소개 + 가벼운 힌트' 중심.\n"
        f'- 2~4문장. 도깨비 말투(어미 "~니라/~겠느냐", 감탄 "허허") 유지.\n'
        f"- 사용자 진행 단계({state.get('stage', '등장')})에 맞는 대사만: 등장 / 의뢰 / 힌트 / 완료.\n\n"
        f"[컨텍스트]\n"
        f"- 사용자 진행상황: {progress_line(state.get('player_state'))}"
        f"   - 사용자 발화: {state.get('query', '')}"
    )
    # (A1 QA 재생성) 직전 출력이 반려된 이유를 그대로 실어 보낸다 — 같은 호출 재시도가
    # 아니라 "무엇이 틀렸는지 알려주고 다시 쓰게 하는" 재생성이어야 한다.
    if state.get("qa_feedback"):
        prompt += (
            f"\n\n[재작성 지시]\n{state['qa_feedback']}\n"
            f"위 지적을 반드시 반영해 대사를 다시 쓴다."
        )
    return {"prompt": prompt}
