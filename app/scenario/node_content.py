# ============================================================
# [v1] 노드 미션 생성 — 타입별 다양화 (생성 시 1회)
# pipeline: AI 백엔드 / 시나리오 (고정 콘텐츠 = 노드당 미션 1개)
# 구현(요약): 노드마다 미션 타입을 순환 배정(PHOTO/COLLECT/DIALOGUE/FIND/QUIZ) →
#            타입별 프롬프트로 grounding 콘텐츠 생성. 모든 미션에 지령(order)+단계힌트.
#            앱 호환: 질문형(QUIZ/DIALOGUE)은 quiz로도 매핑. 아키텍처 3-5 · 시나리오_MVP_예시.
# 구현일: 2026-06-19 | 작성: kys (node-content/kys/v1)
# ============================================================
import json

from app.core.logger import get_logger
from app.llm.client import LLMClient

logger = get_logger(__name__)
_llm = LLMClient()

# 노드 순서대로 순환 배정 → 매 노드 다른 미션 (피날레는 DIALOGUE_COLLECT)
# 앞쪽에 AR 액션형(사냥/복원/추적)을 둬서 짧은(5노드) 코스에서도 다양하게 노출
MISSION_CYCLE = [
    "HUNT", "RESTORE_AR", "PHOTO_FIND", "PATH_TRACE",
    "COLLECT", "DIALOGUE_FIND", "FIND", "QUIZ_FIND",
]


def assign_mission_type(index: int, is_finale: bool) -> str:
    return "DIALOGUE_COLLECT" if is_finale else MISSION_CYCLE[index % len(MISSION_CYCLE)]


_BASE = "너는 '{name}'을(를) 지키는 도깨비다. 도깨비 말투(~니라/허허). 아래 [장소 정보]에 근거해서만, 없는 사실은 지어내지 마라.\n[장소 정보] {overview}\n"

_PROMPTS = {
    "PHOTO_FIND": _BASE + (
        "미션: 사진 촬영 → 먹물 발자국 추적 → 파편 수집.\n"
        '아래 JSON만: {{"photo_targets":["<촬영할 건축/풍경 요소>","<..>"],'
        '"find":"<찾을 파편 이름>","order":"<지령 1줄>","hints":["<힌트1 넓게>","<힌트2 구체적>"]}}'
    ),
    "COLLECT": _BASE + (
        "미션: AR로 이 장소 테마에 맞는 재료/오브젝트를 모으기.\n"
        '아래 JSON만: {{"items":["<재료1>","<재료2>","<재료3>","<재료4>"],'
        '"reactions":["<탭할 때 도깨비 반응1>","<반응2>"],"order":"<지령 1줄>","hints":["<힌트1>","<힌트2>"]}}'
    ),
    "DIALOGUE_FIND": _BASE + (
        "미션: 도깨비 질문에 선택지로 답 → 정답이면 AR 오브젝트 활성화.\n"
        '아래 JSON만: {{"question":"<장소 관련 질문>","options":["<선택1>","<선택2>","<선택3>","<선택4>"],'
        '"answer":<정답 0-3 정수>,"find":"<찾을 오브젝트>","order":"<지령 1줄>","hints":["<힌트1>"]}}'
    ),
    "FIND": _BASE + (
        "미션: AR 카메라로 떠다니는 오브젝트를 찾아 수집(특수 조건 포함).\n"
        '아래 JSON만: {{"object":"<떠다니는 오브젝트>","count":<3-5 정수>,'
        '"special":"<특수 조건 1문장, 예: 천천히 돌려야 사라지지 않음>","order":"<지령 1줄>","hints":["<힌트1>","<힌트2>"]}}'
    ),
    "QUIZ_FIND": _BASE + (
        "미션: 4지선다 퀴즈 정답 → 잠긴 곳 개봉 → 파편. 정답은 [장소 정보]에서 검증 가능해야 한다.\n"
        '아래 JSON만: {{"q":"<문제>","options":["<1>","<2>","<3>","<4>"],"answer":<0-3 정수>,'
        '"wrong_hint":"<오답 힌트, 정답 직접노출 금지>","find":"<찾을 파편>","order":"<지령 1줄>","hints":["<힌트1>"]}}'
    ),
    "HUNT": _BASE + (
        "미션: AR 카메라로 이 장소에 깃든 '망각귀'(잊혀진 기억이 뒤틀린 괴물)를 사냥. 마지막에 미니보스.\n"
        '아래 JSON만: {{"monster":"<이 장소 테마의 망각귀 이름>","count":<3-7 정수>,'
        '"boss":"<마지막 미니보스 이름>","weakness":"<약점/공략 1문장>","order":"<지령 1줄>","hints":["<힌트1>","<힌트2>"]}}'
    ),
    "RESTORE_AR": _BASE + (
        "미션: 사라지거나 무너진 옛 건물/구조물을 AR로 복원. 흩어진 부재(주춧돌·기둥 등)를 제자리에 맞춘다.\n"
        '아래 JSON만: {{"structure":"<복원할 옛 건물/구조물>","parts":["<흩어진 부재1>","<부재2>","<부재3>"],'
        '"era":"<시대>","order":"<지령 1줄>","hints":["<힌트1>","<힌트2>"]}}'
    ),
    "PATH_TRACE": _BASE + (
        "미션: 먹물 발자국을 따라 주변 지점들을 순서대로 밟아 파편에 도달.\n"
        '아래 JSON만: {{"trail_clue":"<발자국 묘사 1문장>","steps":["<거쳐갈 지점/단서1>","<지점2>","<지점3>"],'
        '"find":"<도착지에서 찾을 것>","order":"<지령 1줄>","hints":["<힌트1>"]}}'
    ),
    "DIALOGUE_COLLECT": _BASE + (
        "미션: 최종장. 망각귀의 비관 대사 + 수호 도깨비의 답 + 모은 조각을 순서대로 맞춰 복원하라는 지령.\n"
        '아래 JSON만: {{"villain_line":"<망각귀 비관 대사>","guardian_line":"<수호 도깨비의 답>",'
        '"order":"<복원 지령 1줄>","hints":["<힌트1>"]}}'
    ),
}


async def generate_mission(name: str, overview: str, mtype: str) -> dict:
    """타입별 미션 콘텐츠 생성. 실패해도 폴백(항상 order+hints 보장)."""
    prompt = _PROMPTS.get(mtype, _PROMPTS["FIND"]).format(name=name, overview=(overview or "")[:1500])
    try:
        raw = await _llm.generate(prompt)
        data = _json(raw) or {}
    except Exception as e:
        logger.warning("미션 생성 실패(%s) %s: %s", mtype, name, e)
        data = {}
    return _normalize(mtype, data, name)


def _json(raw: str) -> dict | None:
    try:
        return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except Exception:
        return None


def _norm_hints(d: dict) -> list[str]:
    hints = [h for h in (d.get("hints") or []) if isinstance(h, str) and h.strip()]
    return hints[:2] if hints else ["주변을 천천히 둘러보거라.", "오래되고 그늘진 곳을 살펴보거라."]


def _normalize(mtype: str, d: dict, name: str) -> dict:
    """타입별 정규화 + 폴백. 공통: type, order, hints."""
    m = {
        "type": mtype,
        "order": str(d.get("order") or f"{name}에서 기억석 조각을 찾아라."),
        "hints": _norm_hints(d),
    }
    if mtype == "PHOTO_FIND":
        m["photo_targets"] = _strs(d.get("photo_targets"), ["대문", "전통 건물 외관"])
        m["find"] = str(d.get("find") or "기억석 파편")
    elif mtype == "COLLECT":
        m["items"] = _strs(d.get("items"), ["흩어진 조각", "옛 흔적", "빛 가루", "낡은 문양"])
        m["reactions"] = _strs(d.get("reactions"), ["허허, 조심히 다루거라.", "장인의 기억은 쉬이 흩어지느니."])
    elif mtype == "DIALOGUE_FIND":
        m["question"] = str(d.get("question") or f"{name}의 기억은 어디에 남아 있을까?")
        m["options"] = _strs(d.get("options"), ["오래된 골목", "닫힌 문 안쪽", "높은 담장", "사람들의 발길"])
        m["answer"] = _ans(d.get("answer"), m["options"])
        m["find"] = str(d.get("find") or "기와 조각")
    elif mtype == "FIND":
        m["object"] = str(d.get("object") or "시간의 조각")
        m["count"] = d.get("count") if isinstance(d.get("count"), int) and 1 <= d["count"] <= 9 else 5
        m["special"] = str(d.get("special") or "천천히 둘러보거라. 서두르면 사라지느니라.")
    elif mtype == "QUIZ_FIND":
        m["q"] = str(d.get("q") or f"{name}에 대한 설명으로 옳은 것은?")
        m["options"] = _strs(d.get("options"), ["보기1", "보기2", "보기3", "보기4"])
        m["answer"] = _ans(d.get("answer"), m["options"])
        m["wrong_hint"] = str(d.get("wrong_hint") or "다시 살펴보거라.")
        m["find"] = str(d.get("find") or "기억석 파편")
    elif mtype == "HUNT":
        m["monster"] = str(d.get("monster") or "망각귀")
        m["count"] = d.get("count") if isinstance(d.get("count"), int) and 1 <= d["count"] <= 9 else 5
        m["boss"] = str(d.get("boss") or "흑묵 망령")
        m["weakness"] = str(d.get("weakness") or "도깨비불을 비추면 약해지느니라.")
    elif mtype == "RESTORE_AR":
        m["structure"] = str(d.get("structure") or "옛 전각")
        m["parts"] = _strs(d.get("parts"), ["주춧돌", "기둥", "지붕 부재"])
        m["era"] = str(d.get("era") or "옛 시절")
    elif mtype == "PATH_TRACE":
        m["trail_clue"] = str(d.get("trail_clue") or "먹빛 발자국이 희미하게 이어지느니라.")
        m["steps"] = _strs(d.get("steps"), ["첫 번째 갈림길", "오래된 나무 곁", "담장 끝"])
        m["find"] = str(d.get("find") or "기억석 파편")
    elif mtype == "DIALOGUE_COLLECT":
        m["villain_line"] = str(d.get("villain_line") or "작은 것들은 곧 잊히는 법이지.")
        m["guardian_line"] = str(d.get("guardian_line") or "아니다. 기억은 누군가 다시 찾을 때 살아나느니라.")
    return m


def _strs(v, fallback: list[str]) -> list[str]:
    out = [str(x) for x in v if isinstance(x, (str, int)) and str(x).strip()] if isinstance(v, list) else []
    return out or fallback


def _ans(v, options: list[str]) -> int:
    return v if isinstance(v, int) and 0 <= v < len(options) else 0


def to_quiz(mission: dict) -> dict | None:
    """앱 호환: 질문형 미션(QUIZ/DIALOGUE)을 quiz dict로 매핑. 아니면 None."""
    if mission.get("type") == "QUIZ_FIND":
        return {"q": mission["q"], "options": mission["options"], "answer": mission["answer"],
                "wrong_hint": mission["wrong_hint"]}
    if mission.get("type") == "DIALOGUE_FIND":
        return {"q": mission["question"], "options": mission["options"], "answer": mission["answer"],
                "wrong_hint": "다시 골라 보거라."}
    return None
