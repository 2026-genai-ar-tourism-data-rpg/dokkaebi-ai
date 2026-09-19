# ============================================================
# [v1] 노드 미션 생성 — 타입별 다양화 (생성 시 1회)
# pipeline: AI 백엔드 / 시나리오 (고정 콘텐츠 = 노드당 미션 1개)
# 구현(요약): 노드마다 미션 타입을 순환 배정(PHOTO/COLLECT/DIALOGUE/FIND/QUIZ) →
#            타입별 프롬프트로 grounding 콘텐츠 생성. 모든 미션에 지령(order)+단계힌트.
#            앱 호환: 질문형(QUIZ/DIALOGUE)은 quiz로도 매핑. 아키텍처 3-5 · 시나리오_MVP_예시.
# 구현일: 2026-06-19 | 작성: kys (node-content/kys/v1)
# ------------------------------------------------------------
# [v2] 동기 분류(LLM 1차 · 휴리스틱 폴백) 추가 — #30 노드 스키마 생성층
# 구현(요약): classify_motivations() 신설 — overview를 읽고 닫힌 어휘(M1~M9)만
#            반환하는 grounding 분류. 실패/mock/비JSON이면 호출측 폴백 사용(테스트 결정성).
#            assign_mission_type은 하위호환 보존 — 신규 경로는 node_schema.select_mission_type
#            (동기→허용 전략→미션 타입, 미션 텍스트↔액션 모순 차단).
# 구현일: 2026-07-30 | 작성: pjh (node-schema-gen/pjh/v1)
# ------------------------------------------------------------
# [v3] 미션 생성 실패를 조용히 삼키지 않는다 — 실패는 예외로 올린다.
# 구현(요약): generate_mission이 LLM 오류·JSON 파싱 실패를 잡아 제네릭 미션으로
#            바꿔 돌려주는 바람에 호출측이 "생성됐지만 내용이 텅 빈" 미션을 그대로
#            내보냈다 → MissionGenerationError를 raise하고, 제네릭 폴백은
#            generic_mission()으로 분리(폴백 자체는 그대로 유지). 재시도·폴백 결정은
#            generator._content_for가 한다. feedback= 인자로 QA 재생성 지시를 싣는다.
# 구현일: 2026-09-04 | 작성: pjh (agent-qa/pjh/v1)
# ------------------------------------------------------------
# [v4] 프롬프트가 안 만드는 필드를 전략이 요구하던 구멍을 막는다(실측 2026-09-09).
# 구현(요약): select_mission_type이 "미션 텍스트↔액션 정합"을 보장한다고 해 놓고,
#            매핑된 전략(_compile_strategy)이 쓰는 필드를 그 타입 프롬프트가 안 만들었다.
#            · PATH_TRACE→S4는 photo_targets가 없어 촬영 대상이 늘 ["대문","마당",
#              "전통건물 외관"] — 탑골공원 팔각정엔 대문도 마당도 없다.
#            · PHOTO_FIND→S4는 trail_clue/steps가 없어 발자국이 늘 "먹물 발자국" 3걸음.
#            · HUNT→S2는 find가 없어 파편이 늘 "글씨파편".
#            → 해당 키를 각 프롬프트에 추가한다.
#            또 trail_clue(묘사 1문장)가 follow.object로 쓰여 success 문자열에 문장이
#            통째로 박혔다("follow:검은 먹물이 번진 발자국이 … 이어졌다>=3") →
#            짧은 이름 trail_object를 따로 받는다(묘사는 대사용으로 그대로 둔다).
#            힌트 개수도 타입마다 1개/2개로 갈려 사다리 H2가 범용으로 떨어졌다 → 전부 2개.
# 구현일: 2026-09-09 | 작성: pjh (agent-qa/pjh/v1)
# ------------------------------------------------------------
# [v5] 미션 텍스트도 대사와 같은 필터를 통과시킨다 + 원문 없음 제동(점검 20260909-2).
# 구현(요약): ① clean_line이 대사 경로에만 걸려 있었다. 앱은 objective.order와
#              hint_ladder도 서식 없는 Text로 그리는데, 이 경로는 필터가 없어
#              "**팔각정** 아래를 살펴라. <br>", "(손짓하며) …", "… (규칙에 맞춰
#              구성했습니다)"가 그대로 화면에 나갈 수 있었다 — 결함보고 20260904 #1과
#              2026-09-09 ③이 미션 경로로 그대로 재현된다.
#            ② overview 조회 실패 노드(원문 빈 값)에 "정답은 [장소 정보]에서 검증
#              가능해야 한다"고만 요구했다 — 근거가 없으니 퀴즈를 통째로 창작한다.
#              대사 경로의 NO_SOURCE_RULE과 짝인 NO_SOURCE_MISSION_RULE을 붙인다.
#            ③ DIALOGUE_FIND에 wrong_hint 슬롯이 없어 to_quiz가 고정 문구
#              "다시 골라 보거라."를 넣었고, 그게 사다리 H3을 먹어 마지막 힌트가 늘
#              범용이었다(2026-09-09 ⑥의 잔재). 프롬프트에 슬롯을 만든다.
#            ⑤ 힌트가 힌트가 아니라 **장소 설명**으로 나왔다(실 LLM 주행 20260909-2:
#              "건청궁은 고종과 명성황후의 생활공간으로 1873년에 지어졌다"). 슬롯 설명이
#              "<힌트1 넓게>"뿐이라 모델이 개요 요약을 넣었다. 난이도 '어려움'은 H1 한 칸만
#              노출되므로, H1이 설명문이면 그 노드는 힌트가 아예 없는 것과 같다.
#            ④ 지령이 문장이 아니라 '토큰 목록'으로 나왔다(실 LLM 주행 20260909-2,
#              K-컬처 스크린): "1.망각귀_대마왕_조각 2.수호도깨비_반지 3.…_파편".
#              앱은 이 값을 한 줄 지령으로 그린다 — 프롬프트로 문장을 요구하고,
#              그래도 섞여 나오는 밑줄은 정리한다(모델이 식별자처럼 쓰는 버릇).
# 구현일: 2026-09-09 | 작성: pjh (agent-qa/pjh/v1)
# ------------------------------------------------------------
# [v6] 발자국 추적 → 도깨비가 흘리고 간 엽전 줍기(앱 AR 연출이 엽전으로 바뀜).
# 구현(요약): PHOTO_FIND·PATH_TRACE 프롬프트와 LLM 실패 시 기본값(trail_object·
#            trail_clue, 단일 출처 node_schema)을 엽전으로. 필드 이름(trail_*)·steps 구조는 그대로.
# 구현일: 2026-09-18 | 작성: ljs (coin-trail/ljs/v1)
# ============================================================
import json
import re

from app.core.exceptions import MissionGenerationError
from app.core.logger import get_logger
from app.core.wording import NO_SOURCE_MISSION_RULE, clean_line
from app.llm.client import get_llm
# 폴백 오답 힌트의 단일 출처는 node_schema다 — 같은 문구를 양쪽에 적어 두면 한쪽만 고쳐
# 사다리(H3)가 다시 범용으로 떨어진다. node_schema는 app 의존이 없어 순환하지 않는다.
from app.scenario.node_schema import (
    GENERIC_QUIZ_WRONG_HINT,
    GENERIC_WRONG_HINT,
    TRAIL_CLUE_DEFAULT,
    TRAIL_OBJECT_DEFAULT,
)

logger = get_logger(__name__)
_llm = get_llm()

# 노드 순서대로 순환 배정 → 매 노드 다른 미션 (피날레는 DIALOGUE_COLLECT)
# 앞쪽에 AR 액션형(사냥/복원/추적)을 둬서 짧은(5노드) 코스에서도 다양하게 노출
MISSION_CYCLE = [
    "HUNT", "RESTORE_AR", "PHOTO_FIND", "PATH_TRACE",
    "COLLECT", "DIALOGUE_FIND", "FIND", "QUIZ_FIND",
]


def assign_mission_type(index: int, is_finale: bool) -> str:
    """(하위호환) 동기 무관 순환 배정 — 신규 경로는 node_schema.select_mission_type 사용.

    v3: 이 함수는 동기 제약을 모르므로 미션 텍스트↔전략 모순을 만들 수 있다.
    generator는 select_mission_type(동기 → 허용 전략 → 미션 타입)을 쓴다.
    """
    return "DIALOGUE_COLLECT" if is_finale else MISSION_CYCLE[index % len(MISSION_CYCLE)]


# ── 동기 분류(LLM 1차 · 휴리스틱 폴백) — 시나리오구조화 4절 grounding 원칙 ──
# overview(열린 세계 텍스트)를 읽는 판단은 LLM 층의 일이고, 출력은 닫힌 어휘(M1~M9)라
# 코드가 검증·리롤한다. 실패·미구성(mock)·비JSON이면 호출측이 준 휴리스틱 폴백을 쓴다.

_MOTIVATION_CODES = frozenset(f"M{i}" for i in range(1, 10))

_CLASSIFY_PROMPT = (
    "너는 관광지 설명을 읽고 퀘스트 동기 코드를 1~2개 고르는 분류기다.\n"
    "코드: M1 기억의 수호(역사·이야기가 잊힘) / M2 터 지킴(**현재 진행형** 위협·훼손) / "
    "M3 이름 회복(인물의 명예·업적) / M4 평온 회복(자연·소란 진정) / M5 요괴 소탕 / "
    "M6 살림 불림(시장·상권·소비) / M7 재주 시험(퀴즈·눈썰미) / "
    "M8 물건 되찾기(**현재** 분실물) / M9 위로·전언(인물의 부탁·미련)\n"
    "주의: 과거에 파괴·소실됐다가 복원·중건된 역사 서술은 M2/M8이 아니라 M1/M3이다.\n"
    "[장소] {name}\n[설명] {overview}\n"
    '다른 말 없이 아래 JSON만 출력: {{"motivations":["M?","M?"]}}'
)


async def classify_motivations(name: str, overview: str, fallback: list[str]) -> list[str]:
    """overview 기반 동기 분류. 출력은 항상 검증된 M코드 1~2개(실패 시 fallback)."""
    if not (overview or "").strip():
        return fallback
    prompt = _CLASSIFY_PROMPT.format(name=name or "이곳", overview=overview[:1200])
    try:
        raw = await _llm.generate(prompt)
        data = _json(raw) or {}
    except Exception as e:
        logger.warning("동기 분류 실패(%s): %s → 휴리스틱 폴백", name, e)
        return fallback
    codes = [
        c.strip().upper()
        for c in (data.get("motivations") or [])
        if isinstance(c, str) and c.strip().upper() in _MOTIVATION_CODES
    ]
    codes = list(dict.fromkeys(codes))[:2]
    return codes or fallback


_BASE = (
    "너는 '{name}'을(를) 지키는 도깨비다. 도깨비 말투(~니라/허허). 아래 [장소 정보]에 근거해서만, 없는 사실은 지어내지 마라.\n"
    "[장소 정보] {overview}\n"
    # 앱은 order·hints를 화면에 한 줄씩 그대로 그린다 — 목록·번호·밑줄은 글자로 보인다.
    "지령(order)과 힌트(hints)는 플레이어가 읽는 자연스러운 한국어 한 문장이다. "
    "번호 매기기·목록 기호·밑줄(_)로 단어를 잇는 표기를 쓰지 마라.\n"
)

_PROMPTS = {
    "PHOTO_FIND": _BASE + (
        # [fire-capture] 촬영·OCR 대신 '도깨비불 길들이기'(제자리에서 폰을 돌려 불빛 3마리를 2초씩
        # 조준해 모은다). 지령·힌트가 "찍어라/담아라"를 말하면 앱 행동과 모순된다.
        "미션: 이 장소 골목에 흩어진 도깨비불 세 마리를 폰을 천천히 돌려 가운데에 두고 잠시 붙잡아 초롱에 담는다. "
        "촬영·사진·글자 읽기는 하지 않는다.\n"
        '아래 JSON만: {{"photo_targets":["<불빛이 숨은 이 장소의 요소 1>","<요소 2>","<요소 3>"],'
        '"trail_object":"<도깨비가 흘린 엽전의 짧은 이름, 4~10자>","trail_clue":"<흘린 엽전이 이어진 모습 묘사 1문장>",'
        '"steps":["<거쳐갈 지점1>","<지점2>","<지점3>"],'
        '"find":"<찾을 파편 이름>","order":"<지령 1줄 — 불빛을 모아 초롱을 깨우라는 말. 찍어라/담아라(사진) 금지>",'
        '"hints":["<힌트1: 불빛이 어느 쪽에 흩어졌는지 장소 요소로 넓게 짚는 한 문장>","<힌트2: 폰을 천천히 돌려 가운데에 두고 잠시 멈추라는 조작 힌트 한 문장>"]}}'
    ),
    "COLLECT": _BASE + (
        "미션: AR로 이 장소 테마에 맞는 재료/오브젝트를 모으기.\n"
        '아래 JSON만: {{"items":["<재료1>","<재료2>","<재료3>","<재료4>"],'
        '"reactions":["<탭할 때 도깨비 반응1>","<반응2>"],"order":"<지령 1줄>","hints":["<힌트1: 어디를 살펴야 하는지 넓게 짚어 주는 한 문장. 장소 설명이 아니라 찾는 행동을 이끄는 말>","<힌트2: 찾을 대상 바로 곁을 짚어 주는 구체적인 한 문장>"]}}'
    ),
    "DIALOGUE_FIND": _BASE + (
        "미션: 도깨비 질문에 선택지로 답 → 정답이면 AR 오브젝트 활성화.\n"
        '아래 JSON만: {{"question":"<장소 관련 질문>","options":["<선택1>","<선택2>","<선택3>","<선택4>"],'
        '"answer":<정답 0-3 정수>,"wrong_hint":"<오답일 때 줄 힌트, 이 장소의 것으로. 정답 직접노출 금지>",'
        '"find":"<찾을 오브젝트>","order":"<지령 1줄>","hints":["<힌트1: 어디를 살펴야 하는지 넓게 짚어 주는 한 문장. 장소 설명이 아니라 찾는 행동을 이끄는 말>","<힌트2: 찾을 대상 바로 곁을 짚어 주는 구체적인 한 문장>"]}}'
    ),
    "FIND": _BASE + (
        "미션: AR 카메라로 떠다니는 오브젝트를 찾아 수집(특수 조건 포함).\n"
        '아래 JSON만: {{"object":"<떠다니는 오브젝트>","count":<3-5 정수>,'
        '"special":"<특수 조건 1문장, 예: 천천히 돌려야 사라지지 않음>","order":"<지령 1줄>","hints":["<힌트1: 어디를 살펴야 하는지 넓게 짚어 주는 한 문장. 장소 설명이 아니라 찾는 행동을 이끄는 말>","<힌트2: 찾을 대상 바로 곁을 짚어 주는 구체적인 한 문장>"]}}'
    ),
    "QUIZ_FIND": _BASE + (
        "미션: 4지선다 퀴즈 정답 → 잠긴 곳 개봉 → 파편. 정답은 [장소 정보]에서 검증 가능해야 한다.\n"
        '아래 JSON만: {{"q":"<문제>","options":["<1>","<2>","<3>","<4>"],"answer":<0-3 정수>,'
        '"wrong_hint":"<오답 힌트, 정답 직접노출 금지>","find":"<찾을 파편>","order":"<지령 1줄>","hints":["<힌트1: 어디를 살펴야 하는지 넓게 짚어 주는 한 문장. 장소 설명이 아니라 찾는 행동을 이끄는 말>","<힌트2: 찾을 대상 바로 곁을 짚어 주는 구체적인 한 문장>"]}}'
    ),
    "HUNT": _BASE + (
        "미션: AR 카메라로 이 장소에 깃든 '망각귀'(잊혀진 기억이 뒤틀린 괴물)를 사냥. 마지막에 미니보스.\n"
        '아래 JSON만: {{"monster":"<이 장소 테마의 망각귀 이름>","count":<3-7 정수>,'
        '"boss":"<마지막 미니보스 이름>","weakness":"<약점/공략 1문장>","find":"<쓰러뜨린 뒤 주울 파편 이름>",'
        '"order":"<지령 1줄>","hints":["<힌트1: 어디를 살펴야 하는지 넓게 짚어 주는 한 문장. 장소 설명이 아니라 찾는 행동을 이끄는 말>","<힌트2: 찾을 대상 바로 곁을 짚어 주는 구체적인 한 문장>"]}}'
    ),
    "RESTORE_AR": _BASE + (
        "미션: 사라지거나 무너진 옛 건물/구조물을 AR로 복원. 흩어진 부재(주춧돌·기둥 등)를 제자리에 맞춘다.\n"
        '아래 JSON만: {{"structure":"<복원할 옛 건물/구조물>","parts":["<흩어진 부재1>","<부재2>","<부재3>"],'
        '"era":"<시대>","order":"<지령 1줄>","hints":["<힌트1: 어디를 살펴야 하는지 넓게 짚어 주는 한 문장. 장소 설명이 아니라 찾는 행동을 이끄는 말>","<힌트2: 찾을 대상 바로 곁을 짚어 주는 구체적인 한 문장>"]}}'
    ),
    "PATH_TRACE": _BASE + (
        "미션: 도깨비가 흘리고 간 엽전을 주우며 주변 지점들을 순서대로 지나 파편에 도달.\n"
        '아래 JSON만: {{"trail_object":"<도깨비가 흘린 엽전의 짧은 이름, 4~10자>",'
        '"trail_clue":"<흘린 엽전이 이어진 모습 묘사 1문장>","steps":["<거쳐갈 지점/단서1>","<지점2>","<지점3>"],'
        '"photo_targets":["<자취 끝에서 불빛이 숨은 이 장소의 요소>","<..>"],'
        '"find":"<도착지에서 찾을 것>","order":"<지령 1줄>","hints":["<힌트1: 어디를 살펴야 하는지 넓게 짚어 주는 한 문장. 장소 설명이 아니라 찾는 행동을 이끄는 말>","<힌트2: 찾을 대상 바로 곁을 짚어 주는 구체적인 한 문장>"]}}'
    ),
    "DIALOGUE_COLLECT": _BASE + (
        "미션: 최종장. 망각귀의 비관 대사 + 수호 도깨비의 답 + 모은 조각을 순서대로 맞춰 복원하라는 지령.\n"
        '아래 JSON만: {{"villain_line":"<망각귀 비관 대사>","guardian_line":"<수호 도깨비의 답>",'
        '"order":"<복원 지령 1줄>","hints":["<힌트1: 어디를 살펴야 하는지 넓게 짚어 주는 한 문장. 장소 설명이 아니라 찾는 행동을 이끄는 말>","<힌트2: 찾을 대상 바로 곁을 짚어 주는 구체적인 한 문장>"]}}'
    ),
}


async def generate_mission(name: str, overview: str, mtype: str, *, feedback: str = "") -> dict:
    """타입별 미션 콘텐츠 생성. 실패는 **MissionGenerationError로 올린다**.

    feedback: 직전 출력이 QA를 통과하지 못한 이유(재생성 지시). 비어 있으면 최초 생성.
    ⚠️ 예전에는 실패를 안에서 삼켜 제네릭 미션을 돌려줬다 — 호출측이 실패를 알 수 없어
       재시도도, 사용자 고지도 불가능했다. 폴백은 generic_mission()으로 분리했다.
    """
    prompt = _PROMPTS.get(mtype, _PROMPTS["FIND"]).format(name=name, overview=(overview or "")[:1500])
    if not (overview or "").strip():
        # 이름만 아는 노드(detailCommon2 실패·합성 노드). 대사 경로(NO_SOURCE_RULE)와 짝.
        prompt += f"{NO_SOURCE_MISSION_RULE}\n"
    if feedback:
        prompt += f"\n[재작성 지시] {feedback}\n같은 실수를 반복하지 말고 JSON만 다시 출력하라."
    try:
        raw = await _llm.generate(prompt)
    except Exception as e:
        logger.warning("미션 생성 LLM 호출 실패(%s) %s: %s", mtype, name, e)
        raise MissionGenerationError(f"LLM 호출 실패: {e}") from e
    data = _json(raw)
    if data is None:
        logger.warning("미션 생성 JSON 파싱 실패(%s) %s", mtype, name)
        raise MissionGenerationError("LLM 출력 JSON 파싱 실패")
    return _normalize(mtype, data, name)


def generic_mission(name: str, mtype: str) -> dict:
    """생성 실패 시 제네릭 폴백 미션 — 기존 폴백 동작 그대로(항상 order+hints 보장)."""
    return _normalize(mtype, {}, name)


# 앱이 서식 없는 Text로 그리는 값들 — 대사와 같은 필터를 통과시킨다. type은 식별자라 제외.
_RAW_KEYS = {"type", "answer", "count"}


# 모델이 단어를 식별자처럼 밑줄로 잇는다("망각귀_대마왕_조각"). 앱은 이 값을 문장으로
# 그리므로 글자 사이 밑줄만 공백으로 되돌린다. ⚠️ 미션 텍스트 전용 — 대사에는 걸지 않는다
# (내부 id는 애초에 humanize_ref가 사람 말로 바꾸고, 대사에 밑줄이 나올 일이 없다).
_WORD_UNDERSCORE_RE = re.compile(r"(?<=[0-9A-Za-z가-힣])_(?=[0-9A-Za-z가-힣])")


def _clean_mission_text(mission: dict) -> dict:
    """미션의 화면 노출 문자열에서 마크업·연기 지문·메타 꼬리·밑줄 표기를 걷어낸다.

    ⚠️ 걷어낸 결과가 비면 원문을 남긴다 — clean_line과 같은 계약(빈 값이 더 나쁘다).
    """
    def _one(text: str) -> str:
        return clean_line(_WORD_UNDERSCORE_RE.sub(" ", text)) or text

    for key, value in mission.items():
        if key in _RAW_KEYS:
            continue
        if isinstance(value, str):
            mission[key] = _one(value)
        elif isinstance(value, list):
            mission[key] = [_one(item) if isinstance(item, str) else item for item in value]
    return mission


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
        m["trail_object"] = str(d.get("trail_object") or TRAIL_OBJECT_DEFAULT)
        m["trail_clue"] = str(d.get("trail_clue") or TRAIL_CLUE_DEFAULT)
        m["steps"] = _strs(d.get("steps"), ["첫 번째 갈림길", "오래된 나무 곁", "담장 끝"])
        m["find"] = str(d.get("find") or "기억석 파편")
    elif mtype == "COLLECT":
        m["items"] = _strs(d.get("items"), ["흩어진 조각", "옛 흔적", "빛 가루", "낡은 문양"])
        m["reactions"] = _strs(d.get("reactions"), ["허허, 조심히 다루거라.", "장인의 기억은 쉬이 흩어지느니."])
    elif mtype == "DIALOGUE_FIND":
        m["question"] = str(d.get("question") or f"{name}의 기억은 어디에 남아 있을까?")
        m["options"] = _strs(d.get("options"), ["오래된 골목", "닫힌 문 안쪽", "높은 담장", "사람들의 발길"])
        m["answer"] = _ans(d.get("answer"), m["options"])
        m["wrong_hint"] = str(d.get("wrong_hint") or GENERIC_WRONG_HINT)
        m["find"] = str(d.get("find") or "기와 조각")
    elif mtype == "FIND":
        m["object"] = str(d.get("object") or "시간의 조각")
        m["count"] = d.get("count") if isinstance(d.get("count"), int) and 1 <= d["count"] <= 9 else 5
        m["special"] = str(d.get("special") or "천천히 둘러보거라. 서두르면 사라지느니라.")
    elif mtype == "QUIZ_FIND":
        m["q"] = str(d.get("q") or f"{name}에 대한 설명으로 옳은 것은?")
        m["options"] = _strs(d.get("options"), ["보기1", "보기2", "보기3", "보기4"])
        m["answer"] = _ans(d.get("answer"), m["options"])
        m["wrong_hint"] = str(d.get("wrong_hint") or GENERIC_QUIZ_WRONG_HINT)
        m["find"] = str(d.get("find") or "기억석 파편")
    elif mtype == "HUNT":
        m["monster"] = str(d.get("monster") or "망각귀")
        m["count"] = d.get("count") if isinstance(d.get("count"), int) and 1 <= d["count"] <= 9 else 5
        m["boss"] = str(d.get("boss") or "흑묵 망령")
        m["weakness"] = str(d.get("weakness") or "도깨비불을 비추면 약해지느니라.")
        m["find"] = str(d.get("find") or "기억석 파편")
    elif mtype == "RESTORE_AR":
        m["structure"] = str(d.get("structure") or "옛 전각")
        m["parts"] = _strs(d.get("parts"), ["주춧돌", "기둥", "지붕 부재"])
        m["era"] = str(d.get("era") or "옛 시절")
    elif mtype == "PATH_TRACE":
        m["trail_object"] = str(d.get("trail_object") or TRAIL_OBJECT_DEFAULT)
        m["trail_clue"] = str(d.get("trail_clue") or TRAIL_CLUE_DEFAULT)
        m["steps"] = _strs(d.get("steps"), ["첫 번째 갈림길", "오래된 나무 곁", "담장 끝"])
        m["photo_targets"] = _strs(d.get("photo_targets"), [f"{name}의 전경"])
        m["find"] = str(d.get("find") or "기억석 파편")
    elif mtype == "DIALOGUE_COLLECT":
        m["villain_line"] = str(d.get("villain_line") or "작은 것들은 곧 잊히는 법이지.")
        m["guardian_line"] = str(d.get("guardian_line") or "아니다. 기억은 누군가 다시 찾을 때 살아나느니라.")
    return _clean_mission_text(m)


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
        # ⚠️ 고정 문구를 넣으면 그게 사다리 H3이 된다(build_hint_ladder) — 미션이 만든
        #    장소별 오답 힌트를 쓰고, 없을 때만 범용 문구로 떨어뜨린다(v5).
        return {"q": mission["question"], "options": mission["options"], "answer": mission["answer"],
                "wrong_hint": str(mission.get("wrong_hint") or GENERIC_WRONG_HINT)}
    return None