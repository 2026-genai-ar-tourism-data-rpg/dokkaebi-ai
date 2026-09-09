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
# ------------------------------------------------------------
# [v3] 실LLM 시나리오 생성 대사에서 나온 4건을 프롬프트에서 막는다(실측 2026-09-09).
# 구현(요약): ① 단계 목록에 '식음'이 없어 `사용자 진행 단계(식음)에 맞는 대사만:
#              등장 / 의뢰 / 힌트 / 완료`라는 모순된 지시가 나갔다. 단계별 지시를
#              stage에서 직접 만든다.
#            ② 식음 노드 가드가 분기 대화(branching_service)에만 있었다 — 이 경로는
#              식당에서도 조각·의뢰를 말릴 근거가 없었다. 같은 가드를 넣는다.
#            ③ overview 조회 실패 노드는 [장소 실제 정보]가 빈 채로 "근거해서만
#              말하라"고만 했다 → wording.NO_SOURCE_RULE(분기 대화와 공용)을 붙인다.
#            ④ 연기 지문이 대사에 그대로 나갔다("(우렁찬 목소리로)" 등 4/5 노드)
#              → wording.NO_STAGE_DIRECTION_RULE.
#            그 밖에 빈 페르소나 슬롯(`- 모티프: `)과 빈 발화 라벨을 안 찍고,
#            진행상황/발화 줄 사이에 빠져 있던 개행을 넣는다.
# 구현일: 2026-09-09 | 작성: pjh (agent-qa/pjh/v1)
# ============================================================
from app.core.wording import (
    FOOD_CONTENT_RULE,
    NO_SOURCE_RULE,
    NO_STAGE_DIRECTION_RULE,
    progress_line,
)
from app.pipeline.state import DialogueState

# 단계별 '무엇을 말할 차례인가'. stage는 generator가 정한다(등장/완료/식음) —
# 목록에 없는 값이 와도 기본 지시로 떨어뜨린다.
_STAGE_RULES = {
    "등장": "이 장소에 막 도착한 나그네를 맞이하는 첫 대사다. 장소를 소개하고 흥미를 돋운다.",
    "의뢰": "무엇을 찾아야 하는지 의뢰를 건네는 대사다.",
    "힌트": "이미 헤매고 있는 나그네에게 한 걸음 더 좁혀 주는 대사다.",
    "완료": "마지막 장소다. 나그네가 조각을 거의 다 모아 온 것을 알아보고, "
            "모아 온 것을 여기서 하나로 잇자고 맞이하는 대사다. 처음 만난 것처럼 굴지 않는다.",
    "식음": "여기는 조각이 없는, 요기하고 쉬어 가는 자리다.",
}
_STAGE_DEFAULT = "장소를 소개하는 대사다."

# 식음 노드 가드 — 이 자리엔 기억석이 없다(fragment_id 없음 → 앱이 collect를 건너뛴다).
# 조각을 찾으라고 하면 플레이어는 없는 것을 뒤진다(분기 대화 v2와 같은 사유).
_FOOD_RULE = (
    "기억석·조각·의뢰 이야기는 꺼내지 않는다. 여정 중에 한 술 뜨고 가라고 권하는 말만 한다."
)


async def prompt_assemble(state: DialogueState) -> dict:
    """[노드] persona·context(또는 RAG 청크)·stage를 합쳐 최종 프롬프트 생성.

    템플릿 = 기획_통합.md §13-B `npc_dialogue_v1`. 담당: 박준형(프롬프트 설계).
    """
    persona = state.get("persona", {})
    context = state.get("context", "")
    retrieved = state.get("retrieved", [])
    grounding = context or "\n".join(retrieved)
    place_name = state.get("node_name") or state.get("node_id", "")
    stage = state.get("stage", "등장")
    query = str(state.get("query") or "").strip()

    # 빈 값은 아예 찍지 않는다 — `- 모티프: ` 같은 빈 슬롯은 모델에게 잡음이다.
    traits = [
        f"{label}: {value}"
        for label, value in (("모티프", persona.get("motif")),
                             ("아키타입", persona.get("archetype")),
                             ("성격/말투", persona.get("persona")))
        if str(value or "").strip()
    ]

    rules = ["위 '장소 실제 정보'에 근거해서만 역사·문화를 말한다. 정보에 없으면 지어내지 않는다."]
    if stage != "식음":                     # 식음은 찾을 것이 없다 — '힌트'를 말하면 안 된다
        rules.append("추리 유도가 아니라 '장소 소개 + 가벼운 힌트' 중심.")
    rules += [
        '2~4문장. 도깨비 말투(어미 "~니라/~겠느냐", 감탄 "허허") 유지.',
        NO_STAGE_DIRECTION_RULE,
f"지금은 '{stage}' 단계다 — {_STAGE_RULES.get(stage, _STAGE_DEFAULT)}",
    ]
    if stage == "식음":
        rules += [_FOOD_RULE, FOOD_CONTENT_RULE]
    if not grounding.strip():
        # 이름 말고 아는 게 없는 노드(overview 조회 실패) — 지어내지 말라고 못 박는다.
        rules.append(NO_SOURCE_RULE)

    # 식음 노드는 조각 축 밖이라 진행도를 모른다 — 빈 값이 "이제 막 여정을 시작한
    # 참이다"로 풀려서, 3번째 노드인 식당에서 "여정이 막 시작된 참"이라고 말했다.
    context_lines = []
    if stage != "식음" or state.get("player_state"):
        context_lines.append(f"- 사용자 진행상황: {progress_line(state.get('player_state'))}")
    if query:
        context_lines.append(f"- 사용자 발화: {query}")

    prompt = (
        f"[시스템]\n"
        f"너는 '{place_name}'을(를) 수호하는 도깨비 NPC '{persona.get('name', '이름 없는 도깨비')}'다.\n"
        + (f"- {'  - '.join(traits)}\n" if traits else "")
        + f"\n[장소 실제 정보 — RAG 주입]\n"
        f"{grounding}\n\n"
        f"[규칙]\n"
        + "".join(f"- {rule}\n" for rule in rules)
        + (f"\n[컨텍스트]\n" + "\n".join(context_lines) if context_lines else "")
    )
    # (A1 QA 재생성) 직전 출력이 반려된 이유를 그대로 실어 보낸다 — 같은 호출 재시도가
    # 아니라 "무엇이 틀렸는지 알려주고 다시 쓰게 하는" 재생성이어야 한다.
    if state.get("qa_feedback"):
        prompt += (
            f"\n\n[재작성 지시]\n{state['qa_feedback']}\n"
            f"위 지적을 반드시 반영해 대사를 다시 쓴다."
        )
    return {"prompt": prompt}
