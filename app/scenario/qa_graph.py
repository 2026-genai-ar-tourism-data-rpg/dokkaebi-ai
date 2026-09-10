# ============================================================
# [v1] A1 — 생성 QA 대응 루프 (LangGraph subgraph)
# pipeline: AI 백엔드 / 시나리오 (생성 결과 자동 점검 → 문제 출력만 재생성)
# 구현(요약): run_qa가 잡은 결함을 경고 로그로 흘려보내던 것을 루프로 바꾼다 —
#            QA → PASS면 종료 / FAIL이면 실패 사유를 state에 담아 **문제가 된 LLM
#            출력만** 재생성 → 다시 QA. 최대 scenario_qa_max_regen(기본 2)회.
#            그래도 실패하면 결과를 죽이지 않고 qa_flags(사람이 읽는 사유)만 남기고 종료.
#
#   START → qa ─┬─ PASS ─────────────────────────→ END
#               ├─ answer_leak ─→ regen_mission ─→ qa
#               ├─ tone ────────→ regen_dialogue → qa
#               └─ 재생성 초과 / 계약위반 ─→ flag → END
#
# 설계 메모:
# - 전체 시나리오 생성기를 그래프로 옮기지 않는다. **이 QA 루프만** 별도 subgraph다.
# - run_qa의 판정 기준은 손대지 않는다(node_schema). 여기서는 '무엇을 다시 만들지'만 정한다.
# - answer_leak = 힌트에 퀴즈 정답이 샌 것 → 미션/힌트만 다시 만든다(대사는 멀쩡하다).
# - tone = 대사 문제 → 대사만 다시 만든다(미션은 멀쩡하다).
# - hallucination = 게이트 아님(v2) → 재생성 없이 경고만 남긴다.
# - contract 위반은 LLM 문장 품질이 아니라 스키마 결함이다 → 재생성해도 안 고쳐진다.
#   무의미한 LLM 호출 대신 곧장 flag.
# - ⚠️ LLMClient의 429 백오프 재시도와 다른 층이다. 여기 재생성 횟수는 '출력 품질'
#   기준이고, 호출 실패 재시도는 LLMClient가 이미 한다. RetryPolicy로 중복 구현 금지.
# 구현일: 2026-09-04 | 작성: pjh (agent-qa/pjh/v1)
# ------------------------------------------------------------
# [v2] 환각 판정을 **게이트에서 뗀다** — 결함보고 20260904 #2 ① 조치.
# 구현(요약): 실 LLM 점검에서 run_qa의 환각 판정 정밀도가 0/35(참양성 0건)로 나왔다.
#            정상 대사 4개가 전부 반려돼 노드마다 재생성 2회를 더 돌았고(대사 호출
#            4→12회), 그래도 못 고쳐 qa_flags 4건이 매번 응답에 실렸다. 게다가
#            재생성 프롬프트에 실린 _FB_HALLUCINATION 문구("근거 밖 표현: 감탄사,
#            3문장…")를 solar-pro가 대사 본문에 복창해 **프롬프트 지시문이 앱 화면까지
#            새어 나갔다**(결함 #1). 원래 node_schema.run_qa의 주석도 "게이트가 아니라
#            경고 로그용"이라고 못 박아 뒀다 — 설계 의도로 되돌린다.
#            · qa_passed에서 hallucination_flag 제외 → 재생성 트리거 아님
#            · 대사 재생성 지시문에서 _FB_HALLUCINATION 삭제(결함 #1의 유출 경로 차단)
#            · 판정은 버리지 않는다 — 경고 로그 + qa_flags '경고' 항목으로만 남긴다
# 구현일: 2026-09-06 | 작성: pjh (agent-qa/pjh/v1)
# ------------------------------------------------------------
# [v3] 대사 재생성이 생성 경로의 수정을 우회하던 것을 막는다(점검 20260909-2).
# 구현(요약): regen_dialogue가 run_dialogue에 node_name·qa_feedback만 넘기고
#            **npc와 진행도를 안 넘겼다**. 그래서 말투로 반려된 노드만:
#            ① 앱 표시 NPC(synthesize_npc)가 아니라 LLM 합성 이름으로 되돌아가고
#               (2026-09-09에 고친 '이름 두 계통' 결함이 이 경로로 재발)
#            ② 피날레인데 "이제 막 여정을 시작한 참이다"를 받아, 같은 프롬프트 안에서
#               "처음 만난 것처럼 굴지 않는다"와 정면으로 부딪혔다.
#            재생성은 '같은 입력 + 반려 사유'여야 한다 — 입력을 빠뜨리면 그 자체가
#            새 결함이다. 진행도는 generator가 알고 있으므로 run_qa_loop 인자로 받는다.
# 구현일: 2026-09-09 | 작성: pjh (agent-qa/pjh/v1)
# ============================================================
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.config import get_settings
from app.core.logger import get_logger
from app.scenario.node_content import generate_mission, to_quiz
from app.scenario.node_schema import enrich_quest, run_qa
from app.services.dialogue_service import run_dialogue

logger = get_logger(__name__)

# 재생성 지시문 — "왜 반려됐는지"를 다음 LLM 호출에 그대로 싣는다(단순 동일 호출 재시도 금지).
_FB_ANSWER_LEAK = (
    "직전 출력의 힌트에 정답('{answer}')이 직접 노출되었다. "
    "정답 단어를 힌트에 쓰지 말고, 정답을 스스로 떠올리게 하는 우회 단서로 다시 작성하라."
)
_FB_TONE = (
    "직전 대사에 도깨비 말투가 없었다. "
    "'~느니라/~거라/허허/~로다' 같은 도깨비 어미와 감탄을 반드시 넣어 다시 작성하라."
)
# ⚠️ 환각 사유는 재생성 지시문으로 만들지 않는다(v2). 근거 밖 '표현' 목록을 프롬프트에
#    실어 보내면 모델이 그 목록을 대사에 그대로 복창한다(실측: 결함보고 20260904 #1).


class QAState(TypedDict, total=False):
    """A1 QA 루프 상태 — 퀘스트 1개를 점검·보수하는 동안 노드들이 주고받는 dict."""

    quest: dict           # 점검·보수 대상 퀘스트(enrich_quest를 거친 노드)
    source: dict          # grounding 원천 노드(overview·name) — run_qa의 근거
    player_state: dict    # 그 노드 도착 시점의 진행도 — 최초 생성과 같은 입력으로 재생성한다
    qa: dict              # 직전 run_qa 결과(플래그 + unsupported_tokens)
    qa_feedback: str      # 실패 사유 → 다음 LLM 호출에 싣는 재작성 지시
    qa_retry_count: int   # 지금까지 수행한 재생성 횟수
    qa_max_regen: int     # 재생성 상한(config.scenario_qa_max_regen)
    qa_flags: list        # 최종 미해결 사유(사람이 읽는 문장) — 응답 DTO로 나간다


def qa_passed(qa: dict[str, Any]) -> bool:
    """재생성이 필요한 결함이 있는가(없으면 True).

    ⚠️ hallucination_flag는 여기 들어오지 않는다(v2). 휴리스틱 환각 판정은 정밀도가
    낮아 게이트로 쓰면 정상 대사를 반려하고, 그 반려 사유가 프롬프트를 통해 대사로
    새어 나온다. 판정 결과는 버리지 않고 경고(qa_flags)로만 남긴다 — hallucination_only
    참조.
    """
    return not (
        qa.get("answer_leak")
        or not qa.get("tone_ok")
        or not qa.get("contract_ok")
    )


def hallucination_only(qa: dict[str, Any]) -> bool:
    """재생성 대상 결함은 없고 환각 경고만 남은 상태인가(→ flag로 경고만 기록)."""
    return qa_passed(qa) and bool(qa.get("hallucination_flag"))


async def qa(state: QAState) -> dict:
    """[노드] 생성 결과 자동 점검. run_qa를 그대로 재사용하고 결과만 state에 싣는다."""
    quest = state["quest"]
    result = run_qa(quest, state.get("source") or {})
    if not qa_passed(result):
        flags = {k: result[k] for k in ("answer_leak", "tone_ok", "contract_ok")}
        logger.warning("QA 플래그 %s(%s): %s", quest.get("node_id"), quest.get("name"), flags)
    if result.get("hallucination_flag"):
        # 재생성하지 않는다(v2) — 사람이 뒤에서 확인할 수 있게 근거만 남긴다.
        logger.warning("QA 환각 경고(재생성 안 함) %s(%s): 근거 밖 주장=%s",
                       quest.get("node_id"), quest.get("name"), result.get("unsupported_tokens"))
    return {"qa": result}


async def regen_mission(state: QAState) -> dict:
    """[노드] 정답 유출 → **미션/힌트만** 다시 생성. 대사는 건드리지 않는다."""
    quest = dict(state["quest"])
    source = state.get("source") or {}
    mission = quest.get("mission") if isinstance(quest.get("mission"), dict) else None
    count = state.get("qa_retry_count", 0) + 1
    if not mission:                       # 미션이 없으면 재생성할 대상도 없다
        return {"qa_retry_count": state.get("qa_max_regen", 0)}

    feedback = _FB_ANSWER_LEAK.format(answer=_leaked_answer(quest))
    try:
        regenerated = await generate_mission(
            str(quest.get("name") or "이곳"), str(source.get("overview") or ""),
            str(mission.get("type") or ""), feedback=feedback,
        )
    except Exception as e:                # 재생성 실패는 루프를 깨지 않는다(다음 QA에서 flag)
        logger.warning("QA 미션 재생성 실패 %s: %s", quest.get("node_id"), e)
        return {"qa_feedback": feedback, "qa_retry_count": count}

    quest["mission"] = regenerated
    quest["objective"] = {"order": regenerated.get("order", ""), "hints": regenerated.get("hints", [])}
    quest["quiz"] = to_quiz(regenerated)
    # hint_ladder·actions는 미션에서 파생된다 → 다시 컴파일해야 QA가 새 힌트를 본다.
    quest = enrich_quest(quest, source, motivations=quest.get("motivation"))
    return {"quest": quest, "qa_feedback": feedback, "qa_retry_count": count}


async def regen_dialogue(state: QAState) -> dict:
    """[노드] 말투 → **NPC 대사만** 다시 생성. 미션은 건드리지 않는다(환각은 v2에서 제외)."""
    quest = dict(state["quest"])
    source = state.get("source") or {}
    count = state.get("qa_retry_count", 0) + 1
    feedback = _dialogue_feedback(state.get("qa") or {})
    stage = "완료" if quest.get("is_finale") else "등장"
    npc = quest.get("npc") if isinstance(quest.get("npc"), dict) else None
    try:
        # qa_feedback을 넘기면 대사 캐시를 우회한다 — 캐시를 타면 방금 반려한 대사가 돌아온다.
        # ⚠️ npc·진행도는 최초 생성(_dialogue_for)과 **같은 값**을 넘겨야 한다. 빠뜨리면
        #    이 경로만 다른 도깨비가, 다른 진행도로 말한다(v3에서 실제로 그랬다).
        text, _hit = await run_dialogue(
            str(quest.get("node_id") or ""), stage, dict(state.get("player_state") or {}),
            node_name=str(quest.get("name") or ""), qa_feedback=feedback, npc=npc,
        )
    except Exception as e:                # 재생성 실패는 루프를 깨지 않는다(다음 QA에서 flag)
        logger.warning("QA 대사 재생성 실패 %s: %s", quest.get("node_id"), e)
        return {"qa_feedback": feedback, "qa_retry_count": count}

    if text:
        quest["npc_dialogue"] = text
    return {"quest": quest, "qa_feedback": feedback, "qa_retry_count": count}


async def flag(state: QAState) -> dict:
    """[노드] 재생성으로 못 고친 결함 → 결과를 죽이지 말고 사유만 남긴다(응답 DTO로 나감)."""
    quest = state["quest"]
    result = state.get("qa") or {}
    name = str(quest.get("name") or quest.get("node_id") or "이름 없는 노드")
    tries = state.get("qa_retry_count", 0)
    suffix = f"(재생성 {tries}회 후에도 미해결)" if tries else "(재생성 대상 아님)"

    flags = list(state.get("qa_flags") or [])
    if result.get("answer_leak"):
        flags.append(f"{name}: 힌트에 퀴즈 정답 노출 {suffix}")
    if not result.get("tone_ok", True):
        flags.append(f"{name}: NPC 대사에 도깨비 말투 미검출 {suffix}")
    if result.get("hallucination_flag"):
        # v2: 재생성 대상이 아니다 — 확인용 경고임을 문구로 못 박는다.
        tokens = ", ".join(result.get("unsupported_tokens") or [])
        flags.append(f"{name}: [경고] 원문에 없는 주장 — {tokens} (재생성하지 않음, 확인 필요)")
    if not result.get("contract_ok", True):
        flags.append(f"{name}: 앱 노드 계약 위반 — 재생성으로 해결되지 않음(스키마 점검 필요)")
    return {"qa_flags": flags}


def _route_after_qa(state: QAState) -> str:
    """조건 엣지: PASS면 종료 / 실패 원인별로 재생성 대상 선택 / 상한 초과·계약위반이면 flag."""
    result = state.get("qa") or {}
    if qa_passed(result):
        # 환각만 남았으면 재생성 없이 flag에서 경고만 적고 끝낸다(v2).
        return "flag" if hallucination_only(result) else END
    if state.get("qa_retry_count", 0) >= state.get("qa_max_regen", 0):
        return "flag"
    if result.get("answer_leak"):
        return "regen_mission"            # 정답 유출 = 미션/힌트 문제
    if not result.get("tone_ok", True):
        return "regen_dialogue"           # 말투 = 대사 문제
    return "flag"                         # 계약 위반만 남은 경우 — LLM이 고칠 수 없다


def build_qa_graph():
    """[A1] QA 대응 루프 subgraph 조립 후 컴파일해 반환(app/pipeline/graph.py와 같은 패턴)."""
    g = StateGraph(QAState)
    g.add_node("qa", qa)
    g.add_node("regen_mission", regen_mission)
    g.add_node("regen_dialogue", regen_dialogue)
    g.add_node("flag", flag)

    g.add_edge(START, "qa")
    g.add_conditional_edges(
        "qa", _route_after_qa,
        {"regen_mission": "regen_mission", "regen_dialogue": "regen_dialogue",
         "flag": "flag", END: END},
    )
    g.add_edge("regen_mission", "qa")     # 재생성 → 다시 QA
    g.add_edge("regen_dialogue", "qa")
    g.add_edge("flag", END)
    return g.compile()


# 컴파일된 그래프는 1회만 빌드(stateless) — 호출마다 state만 주입(dialogue_service와 동일)
_graph = build_qa_graph()


async def run_qa_loop(quest: dict, source: dict,
                      player_state: dict | None = None) -> tuple[dict, list[str]]:
    """[서비스] 퀘스트 1개에 A1 루프를 돌려 (보수된 퀘스트, 미해결 사유) 반환.

    통과하면 flags는 빈 리스트다. 실패해도 예외를 던지지 않는다 —
    시나리오 생성 자체를 죽이지 않고 사유만 남기는 것이 이 루프의 계약이다.

    player_state: 그 노드 도착 시점의 진행도(generator가 안다). 대사를 다시 만들 때
    최초 생성과 같은 입력을 쓰기 위한 값 — 안 주면 진행도 없이 재생성된다(v3 이전 동작).
    """
    state: QAState = {
        "quest": quest,
        "source": source or {},
        "player_state": dict(player_state or {}),
        "qa_feedback": "",
        "qa_retry_count": 0,
        "qa_max_regen": max(0, get_settings().scenario_qa_max_regen),
        "qa_flags": [],
    }
    result = await _graph.ainvoke(state)
    return result.get("quest", quest), list(result.get("qa_flags") or [])


def _leaked_answer(quest: dict) -> str:
    """힌트로 샌 퀴즈 정답 문자열(재작성 지시에 그대로 넣는다)."""
    quiz = quest.get("quiz") if isinstance(quest.get("quiz"), dict) else {}
    options = quiz.get("options") if isinstance(quiz.get("options"), list) else []
    idx = quiz.get("answer")
    if isinstance(idx, int) and 0 <= idx < len(options):
        return str(options[idx])
    return ""


def _dialogue_feedback(result: dict) -> str:
    """대사 재생성 지시문 — 현재는 말투 사유뿐이다.

    ⚠️ 환각 사유(근거 밖 표현 목록)를 여기 다시 넣지 말 것. 모델이 그 목록을 대사에
    복창해 프롬프트가 앱 화면으로 샌다(결함보고 20260904 #1).
    """
    return _FB_TONE if not result.get("tone_ok", True) else ""
