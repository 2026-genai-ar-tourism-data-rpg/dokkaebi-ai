# ============================================================
# [v1] 2차 점검(20260909-2) 회귀 스위트 — 어제 고친 수정이 '다른 경로'로 새던 것들
# pipeline: AI 백엔드 / 대사·미션 품질 (오프라인·결정론 — 네트워크·실 LLM 0)
# 커버:
#   #1 QA 대사 재생성이 npc·진행도를 그대로 넘긴다(2026-09-09 ①⑤가 이 경로로 재발했다)
#   #2 샛길(b1) 노드도 대체하는 본선 노드의 진행도로 말한다
#   #3 사다리 H3에 '내용 없는' 폴백 오답 힌트를 올리지 않는다(⑥의 잔재)
#   #4 미션 텍스트(지령·힌트)도 대사와 같은 필터를 통과한다(#1·③이 미션 경로로 재현됐다)
#   #5 clean_line이 연도·한자 병기 같은 주석 괄호를 지우지 않는다(③ 안전망의 오탐)
#   #6 대사 캐시 키가 진행도를 포함한다(⑤로 늘어난 프롬프트 입력이 키에 없었다)
#   #7 난이도가 '힌트 칸수'를 실제로 줄인다(품질을 떨어뜨리는 게 아니라)
#   #8 원문 없는 노드의 미션 프롬프트에 제동이 붙는다(⑧이 대사 경로에만 있었다)
#   #9 페르소나 슬롯이 한 줄에 하나씩 찍힌다
#   #10 술 제동이 kind가 아니라 원문 기준으로 걸린다(④의 잔재)
#   #11 동작 명사 지문("(윙크)")도 걷어낸다 — #5를 고치며 좁아진 판정의 구멍
#   #12 지령이 토큰 목록("망각귀_대마왕_조각")이 아니라 문장으로 나간다
#   #13 정답 가리기가 문장을 깨지 않는다 + 유출은 '재생성 사유'로 남는다
# 실 LLM 확인: 위 #11·#12는 이 수정 뒤 solar-pro 주행(종로, 2026-09-09)에서 눈으로 잡은 것.
#
# 규약(1차 스위트와 동일):
#   · "실제 길이의 정상 출력"을 픽스처로 쓴다 — 한 단어짜리 입력은 통과해도 의미가 없다.
#   · 고쳐진 동작만 단언하고, **오탐 방지 케이스를 같이 둔다**. 이번 결함 중 둘(#5·#10)이
#     "결함을 잡으려다 멀쩡한 것을 지운" 안전망이라, 양쪽을 같이 고정하지 않으면 다시 뒤집힌다.
#   · 가짜 함수는 **kwargs로 받는다 — 시그니처를 좁게 고정하면 인자가 늘어난 것을 못 본다
#     (1차 스위트가 #1을 놓친 이유가 그것이다).
# 구현일: 2026-09-09 | 작성: pjh (agent-qa/pjh/v1)
# ============================================================
import asyncio

import pytest

import app.scenario.generator as generator
import app.scenario.node_content as node_content
import app.scenario.qa_graph as qa_graph
from app.core.wording import alcohol_in_source, clean_line, progress_cache_token
from app.pipeline.nodes.persona_inject import persona_inject
from app.pipeline.nodes.prompt_assemble import prompt_assemble
from app.scenario.generator import _build_quest, _plan_nodes, _quest_player_state
from app.scenario.node_content import generate_mission, to_quiz
from app.scenario.node_schema import build_hint_ladder, enrich_quest
from app.scenario.preference import apply_ladder_limit
from app.scenario.route_branching import attach_branch


def _prompt(**state) -> str:
    return asyncio.run(prompt_assemble(state))["prompt"]


def _source(**overrides) -> dict:
    data = {
        "node_id": "tour_126508",
        "name": "탑골공원",
        "content_type_id": 12,
        "cat1": "A02",
        "overview": "탑골공원은 1897년에 조성된 우리나라 최초의 근대식 공원으로, "
                    "1919년 3·1운동이 시작된 곳이다. 원각사지 십층석탑과 팔각정이 남아 있다.",
    }
    data.update(overrides)
    return data


def _mission(**overrides) -> dict:
    """LLM이 정상으로 만들어 주는 길이의 미션(HUNT). 힌트 2개 = 프롬프트가 요구하는 수."""
    data = {
        "type": "HUNT",
        "monster": "먹그림자",
        "count": 3,
        "boss": "흑묵 망령",
        "weakness": "도깨비불을 비추면 약해지느니라.",
        "find": "선언문 조각",
        "order": "팔각정 둘레를 돌며 먹그림자를 몰아내고 선언문 조각을 주워라.",
        "hints": ["공원 한복판에 선 팔각정부터 살펴보거라.",
                  "팔각정 기단 아래 그늘진 틈을 들여다보거라."],
    }
    data.update(overrides)
    return data


def _quest(mission: dict | None = None, **overrides) -> dict:
    """generator._build_quest가 만드는 것과 같은 형태의 관광 퀘스트(enrich 전)."""
    mission = mission if mission is not None else _mission()
    data = {
        "order": 0,
        "node_id": "tour_126508",
        "name": "탑골공원",
        "kind": "spot",
        "mission": mission,
        "quiz": to_quiz(mission),
        "objective": {"order": mission["order"], "hints": mission["hints"]},
        "stone_no": 4,
        "fragment_id": "종로_stone_4of5",
        "npc_dialogue": "허허, 잘 왔느니라.",
        "npc": {"name": "석탑 도깨비", "archetype": "persona", "motif": "탑·돌"},
        "is_finale": False,
    }
    data.update(overrides)
    return data


class _CapturingLLM:
    """호출 프롬프트를 기록하고 정해진 답을 돌려주는 가짜 LLM."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def generate(self, prompt: str, **kwargs) -> str:
        self.prompts.append(prompt)
        return self.reply


# ── #1 QA 대사 재생성이 최초 생성과 같은 입력을 쓴다 ────────────────
# 말투로 반려된 노드만 ① 다른 이름의 도깨비가 ② 다른 진행도로 말했다.

def _run_regen(monkeypatch, quest: dict, player_state: dict) -> dict:
    """regen_dialogue를 한 번 돌리고 run_dialogue에 넘어간 인자를 돌려준다."""
    seen: dict = {}

    async def fake_run_dialogue(node_id, stage, ps, **kwargs):
        seen.update({"node_id": node_id, "stage": stage, "player_state": ps, **kwargs})
        return "허허, 다시 쓴 대사니라.", False

    monkeypatch.setattr(qa_graph, "run_dialogue", fake_run_dialogue)
    asyncio.run(qa_graph.regen_dialogue({
        "quest": quest, "source": _source(), "player_state": player_state,
        "qa": {"tone_ok": False}, "qa_retry_count": 0, "qa_max_regen": 2,
    }))
    return seen


def test_대사_재생성은_앱에_표시되는_npc를_그대로_쓴다(monkeypatch):
    """재생성 경로만 npc를 안 넘겨, 말풍선엔 '석탑 도깨비'인데 대사는 LLM 합성 이름이었다."""
    quest = _quest()

    seen = _run_regen(monkeypatch, quest, {"progress": 3, "required": 5})

    assert seen["npc"] == quest["npc"]          # 이름·모티프가 앱과 갈리지 않는다


def test_피날레_대사_재생성이_진행도를_잃지_않는다(monkeypatch):
    """'처음 만난 것처럼 굴지 않는다'와 '이제 막 여정을 시작한 참이다'가 한 프롬프트에 같이 있었다."""
    quest = _quest(is_finale=True, stone_no=5, fragment_id="종로_stone_5of5")

    seen = _run_regen(monkeypatch, quest, {"progress": 4, "required": 5})

    assert seen["stage"] == "완료"
    assert seen["player_state"] == {"progress": 4, "required": 5}
    # 그 입력이 실제 프롬프트에서 어떻게 보이는지까지 고정한다(문구가 바뀌면 여기서 걸린다).
    prompt = _prompt(node_name=quest["name"], stage="완료", persona={"name": "수호 도깨비"},
                     context=_source()["overview"], player_state=seen["player_state"])
    assert "이제 막 여정을 시작한 참이다" not in prompt
    assert "4조각을 모았다" in prompt


def test_QA_루프가_노드의_진행도를_재생성까지_들고_간다(monkeypatch):
    """run_qa_loop → regen_dialogue로 진행도가 전달되는 배선(끊기면 위 두 테스트가 무의미해진다)."""
    calls: list[dict] = []

    async def fake_run_dialogue(node_id, stage, ps, **kwargs):
        calls.append({"player_state": ps, **kwargs})
        return "허허, 다시 쓴 대사니라.", False

    monkeypatch.setattr(qa_graph, "run_dialogue", fake_run_dialogue)
    monkeypatch.setattr(qa_graph, "run_qa", lambda node, source: {
        "answer_leak": False, "tone_ok": len(calls) > 0, "hallucination_flag": False,
        "unsupported_tokens": [], "contract_ok": True,
    })

    asyncio.run(qa_graph.run_qa_loop(_quest(), _source(), {"progress": 3, "required": 5}))

    assert calls and calls[0]["player_state"] == {"progress": 3, "required": 5}


# ── #2 샛길(b1) 노드도 대체하는 본선 노드의 진행도로 말한다 ──────────

def _linear_sequence() -> tuple[list[dict], list[dict]]:
    route = [
        {"node_id": f"s{i}", "name": name, "map_x": 126.98 + i / 1000, "map_y": 37.57 + i / 1000}
        for i, name in enumerate(["운현궁", "인사동", "공예박물관", "경복궁", "북촌"], start=1)
    ]
    metas = _plan_nodes(route)
    seq = [_build_quest(n, i, metas[i], "종로", f"대사{i}") for i, n in enumerate(route)]
    return route, seq


def test_샛길_노드는_대체하는_본선_노드의_진행도를_쓴다():
    """샛길은 stone_no가 없어 빈 진행도가 됐다 — 코스 중반에 '이제 막 시작한 참'으로 맞이했다."""
    route, seq = _linear_sequence()
    alt = {"order": 9, "node_id": "a1", "name": "샛길터", "kind": "spot",
           "mission": None, "quiz": None, "objective": None, "stone_no": None,
           "fragment_id": "종로_branch_b1", "npc_dialogue": "허허.", "is_finale": False}
    seq2, _tree = attach_branch(seq, 1, alt)
    by_id = {q["node_id"]: q for q in seq2}
    branch = next(q for q in seq2 if q["node_id"] == "a1")

    # 갈림길은 BP(s2) 다음 노드를 대체한다 — 샛길로 새면 s3(3번째 조각)을 건너뛴다.
    # 그 자리에 도착한 플레이어는 s1·s2에서 2조각을 이미 들고 있다.
    assert branch["substitutes"] == "s3"
    assert _quest_player_state(branch, by_id) == {"progress": 2, "required": 5}


def test_생성_경로의_샛길_대사도_진행도를_받는다(monkeypatch):
    """_apply_branching이 대사를 만들 때 넘기는 값 — 여기가 비면 위 계산이 쓰이지 않는다."""
    route, seq = _linear_sequence()
    seen: list[dict] = []

    async def fake_run_dialogue(node_id, stage, player_state, **kwargs):
        seen.append({"node_id": node_id, "stage": stage, "player_state": player_state})
        return "허허, 샛길이니라.", False

    async def fake_overview(node):
        return "샛길터에 남은 옛 담장."

    async def fake_classify(name, overview, fallback):
        return fallback

    monkeypatch.setattr(generator, "run_dialogue", fake_run_dialogue)
    monkeypatch.setattr(generator, "_overview_for", fake_overview)
    monkeypatch.setattr(generator, "classify_motivations", fake_classify)

    reserve = [{"node_id": "a1", "name": "샛길터", "map_x": 126.9815, "map_y": 37.5715}]
    asyncio.run(generator._apply_branching(
        seq, route, reserve, "종로",
        with_dialogue=True, with_content=False, sources={}, flags=[],
    ))

    alt_call = next(c for c in seen if c["node_id"] == "a1")
    assert alt_call["player_state"] == {"progress": 2, "required": 5}


# ── #3 사다리 H3에 '내용 없는' 폴백 오답 힌트를 올리지 않는다 ────────

def test_선택형_미션의_H3이_고정문구로_굳지_않는다():
    """to_quiz가 넣던 '다시 골라 보거라.'가 그대로 H3이 돼 5노드 전부 범용이었다."""
    mission = _mission(type="DIALOGUE_FIND", question="이 터에서 울린 함성은?",
                       options=["만세", "북소리", "종소리", "풍악"], answer=0,
                       find="선언문 조각")
    mission.pop("wrong_hint", None)
    ladder = build_hint_ladder(_quest(mission))

    assert ladder["H3"] != node_content.GENERIC_WRONG_HINT
    assert "선언문 조각" in ladder["H3"]          # 폴백도 미션 대상에서 유도한다


def test_미션이_만든_오답_힌트는_H3으로_쓴다():
    """내용 있는 오답 힌트는 사다리의 마지막 칸으로 쓸 만하다 — 그건 그대로 둔다."""
    mission = _mission(type="DIALOGUE_FIND", question="이 터에서 울린 함성은?",
                       options=["만세", "북소리", "종소리", "풍악"], answer=0,
                       wrong_hint="팔각정 현판에 새겨진 글자를 다시 읽어 보거라.",
                       find="선언문 조각")
    ladder = build_hint_ladder(_quest(mission))

    assert ladder["H3"] == "팔각정 현판에 새겨진 글자를 다시 읽어 보거라."


@pytest.mark.parametrize("generic", ["다시 골라 보거라.", "다시 살펴보거라.",
                                     "장소 정보와 화면의 목표를 다시 대조해 보거라.", ""])
def test_각_층의_폴백_오답_문구가_전부_걸러진다(generic):
    """층마다 다른 폴백 문구를 쓴다 — 하나라도 빠지면 그 미션 타입만 다시 역행한다."""
    mission = _mission(type="QUIZ_FIND", q="3·1운동이 시작된 해는?",
                       options=["1919년", "1945년", "1592년", "1876년"], answer=0,
                       wrong_hint=generic, find="선언문 조각")
    ladder = build_hint_ladder(_quest(mission))

    assert ladder["H3"] != generic
    assert "선언문 조각" in ladder["H3"]


def test_사다리는_구체적으로_내려간다():
    """H1(넓게) → H2(구체) → H3(가장 구체). 역행 여부를 사람이 읽을 수 있게 고정한다."""
    ladder = build_hint_ladder(_quest())

    assert ladder["H1"] == "공원 한복판에 선 팔각정부터 살펴보거라."
    assert ladder["H2"] == "팔각정 기단 아래 그늘진 틈을 들여다보거라."
    assert "선언문 조각" in ladder["H3"]


# ── #4 미션 텍스트도 대사와 같은 필터를 통과한다 ──────────────────

_DIRTY_MISSION_JSON = (
    "요청하신 미션을 아래와 같이 구성했습니다.\n"
    '{"monster":"먹그림자","count":3,"boss":"흑묵 망령","weakness":"도깨비불에 약하니라.",'
    '"find":"선언문 조각",'
    '"order":"**팔각정** 둘레를 돌아라. <br>서두르지 마라.",'
    '"hints":["(손짓하며) 공원 한복판을 보거라.",'
    '"기단 아래를 보거라. (규칙에 맞춰 구성했습니다)"]}'
)


def test_지령과_힌트에서_마크업_지문_메타를_걷어낸다(monkeypatch):
    """앱은 objective.order·hint_ladder도 서식 없는 Text로 그린다 — 대사에만 필터가 있었다."""
    monkeypatch.setattr(node_content, "_llm", _CapturingLLM(_DIRTY_MISSION_JSON))

    mission = asyncio.run(generate_mission("탑골공원", _source()["overview"], "HUNT"))

    assert mission["order"] == "팔각정 둘레를 돌아라.\n서두르지 마라."   # **강조**·<br> 제거
    assert mission["hints"][0] == "공원 한복판을 보거라."               # 연기 지문 제거
    assert mission["hints"][1] == "기단 아래를 보거라."                 # 메타 꼬리 제거
    # 걷어낸 값이 그대로 사다리로 간다(앱이 보는 최종 형태까지 확인).
    ladder = build_hint_ladder(_quest(mission))
    assert "**" not in ladder["H1"] and "(" not in ladder["H1"]


def test_미션_필터가_본문_괄호와_보기를_망가뜨리지_않는다(monkeypatch):
    """필터의 오탐이 미션에서 더 위험하다 — 보기가 사라지면 정답 인덱스가 어긋난다."""
    raw = ('{"q":"이 탑의 본래 이름은?",'
           '"options":["원각사지 십층석탑(圓覺寺址十層石塔)","경천사탑","다보탑","석가탑"],'
           '"answer":0,"wrong_hint":"탑의 층수를 세어 보거라.","find":"석탑 파편",'
           '"order":"석탑 앞에서 파편을 찾아라.","hints":["탑을 보거라.","기단을 보거라."]}')
    monkeypatch.setattr(node_content, "_llm", _CapturingLLM(raw))

    mission = asyncio.run(generate_mission("탑골공원", _source()["overview"], "QUIZ_FIND"))

    assert mission["options"][0] == "원각사지 십층석탑(圓覺寺址十層石塔)"   # 한자 병기 보존
    assert len(mission["options"]) == 4
    assert mission["options"][mission["answer"]].startswith("원각사지")   # 정답 인덱스 유효


# ── #5 clean_line 오탐 — 주석 괄호를 지우지 않는다 ────────────────

@pytest.mark.parametrize("line", [
    "이 종은 세조 때 (1468년) 다시 부어 만든 것이니라.",
    "여기가 보신각 (普信閣)이 선 자리니라.",
    "탑골공원 (Tapgol Park)이라 부르기도 하느니라.",
    "허허, 저 탑은 원각사지 십층석탑(圓覺寺址十層石塔)이니라.",
    "문이 닫혀 있거든 (옆으로 돌아가거라)",
])
def test_주석_괄호와_괄호_대사는_남긴다(line):
    """v3 안전망이 '도깨비 어미로 안 끝나면 지문'이라 연도·병기를 통째로 지웠다."""
    assert clean_line(line) == line


@pytest.mark.parametrize("line, expected", [
    # 실 LLM 주행에서 실제로 앱까지 나간 지문 — 동작 명사 하나짜리도 지문이다.
    ("혹시 기억석 조각도 함께 찾아볼까? (윙크)", "혹시 기억석 조각도 함께 찾아볼까?"),
    ("허허, 잘 왔느니라. (한숨)", "허허, 잘 왔느니라."),
    ("(굽고 있는 장어를 가리키며) 담백하니라", "담백하니라"),
    ("궁금하지 않겠느냐? (단검을 어루만지며) 느껴지느냐?", "궁금하지 않겠느냐? 느껴지느냐?"),
    ("한 점 들거라.\n(좌석을 가리킨 뒤 접시를 내민다)", "한 점 들거라."),
    ("팔각정을 보거라.\n(팔각정 내부를 탐색하라는 힌트)", "팔각정을 보거라."),
])
def test_연기_지문은_그대로_걷어낸다(line, expected):
    """오탐을 막느라 진짜 지문까지 놓치면 안 된다 — 양쪽을 같이 고정한다."""
    assert clean_line(line) == expected


def test_괄호를_지운_자리에_공백이_남지_않는다():
    """'여기가 보신각 이니라.'처럼 지운 흔적이 화면에 보이던 문제."""
    assert "  " not in clean_line("허허 (웃으며) 잘 왔느니라.")


# ── #6 대사 캐시 키가 진행도를 포함한다 ──────────────────────────

def _cache_key(player_state: dict | None) -> str:
    state = {"node_id": "tour_126508", "node_name": "탑골공원", "stage": "등장",
             "player_state": player_state, "npc": {"name": "석탑 도깨비"}}
    return asyncio.run(persona_inject(state))["cache_key"]


def test_진행도가_다르면_대사_캐시_키가_다르다(monkeypatch):
    """같은 장소가 다른 코스에서 2번째·4번째 조각이면 프롬프트가 다르다 — 키도 달라야 한다."""
    monkeypatch.setattr("app.pipeline.nodes.persona_inject._load_persona",
                        lambda *a, **k: _persona())

    second = _cache_key({"progress": 1, "required": 5})
    fourth = _cache_key({"progress": 3, "required": 5})
    fresh = _cache_key({})

    assert second != fourth != fresh
    assert "tour_126508:등장" in second          # 노드·단계 구분은 그대로 유지


def test_같은_진행도면_캐시를_그대로_탄다(monkeypatch):
    """키에 잡음을 넣어 캐시가 사실상 꺼지면 LLM 호출이 노드마다 다시 늘어난다."""
    monkeypatch.setattr("app.pipeline.nodes.persona_inject._load_persona",
                        lambda *a, **k: _persona())

    assert _cache_key({"progress": 2, "required": 5}) == _cache_key({"progress": 2, "required": 5})


def test_진행도_지문은_프롬프트_문장을_따라간다():
    """표기 규칙(progress_line)이 바뀌면 키도 바뀌어야 옛 대사가 남지 않는다."""
    assert progress_cache_token({"progress": 1, "required": 5}) != \
        progress_cache_token({"progress": 2, "required": 5})
    assert progress_cache_token({}) == progress_cache_token(None)


async def _persona():
    return {"name": "석탑 도깨비", "archetype": "persona", "motif": "탑·돌", "persona": "느긋하다."}


# ── #7 난이도가 힌트 '칸수'를 줄인다 ──────────────────────────────

@pytest.mark.parametrize("difficulty, rungs", [("easy", 3), ("normal", 2), ("hard", 1)])
def test_난이도가_노출_힌트_칸수를_정한다(difficulty, rungs):
    """계약(handoff 20260906)은 3/2/1인데, 사다리는 늘 3칸이라 난이도가 안 먹었다."""
    quest = dict(_quest(), hint_ladder=build_hint_ladder(_quest()))

    limited = apply_ladder_limit(quest, difficulty)

    assert [k for k in ("H1", "H2", "H3") if k in limited["hint_ladder"]] == \
        ["H1", "H2", "H3"][:rungs]
    # 해금 규칙도 같이 줄어야 한다 — 남은 칸보다 길면 열 수 없는 조건이 남는다.
    assert len(limited["hint_ladder"]["open_rule"]) == rungs
    assert len(limited["objective"]["hints"]) <= rungs


def test_어려움에서도_남는_힌트는_LLM이_쓴_구체적_힌트다():
    """전에는 미션 hints를 먼저 잘라 H2가 범용 폴백으로 떨어졌다 — 줄이는 게 아니라 나빠졌다."""
    quest = dict(_quest(), hint_ladder=build_hint_ladder(_quest()))

    hard = apply_ladder_limit(quest, "hard")

    assert hard["hint_ladder"]["H1"] == "공원 한복판에 선 팔각정부터 살펴보거라."
    assert "지령이 이르는" not in hard["hint_ladder"]["H1"]      # 폴백 문구가 아니다


def test_힌트_사다리_절단은_원본을_건드리지_않는다():
    """같은 퀘스트로 난이도를 바꿔 다시 만들 수 있어야 한다(제자리 수정 금지)."""
    quest = dict(_quest(), hint_ladder=build_hint_ladder(_quest()))

    apply_ladder_limit(quest, "hard")

    assert set(quest["hint_ladder"]) >= {"H1", "H2", "H3"}


# ── #8 원문 없는 노드의 미션 프롬프트에 제동이 붙는다 ─────────────

def test_원문이_없으면_미션_프롬프트에_제동이_붙는다(monkeypatch):
    """빈 [장소 정보]에 '정답은 장소 정보에서 검증 가능해야 한다'만 요구해 퀴즈를 창작했다."""
    llm = _CapturingLLM('{"q":"?","options":["1","2","3","4"],"answer":0,'
                        '"wrong_hint":"간판을 보거라.","find":"파편","order":"살펴라.",'
                        '"hints":["둘러보거라.","가까이 보거라."]}')
    monkeypatch.setattr(node_content, "_llm", llm)

    asyncio.run(generate_mission("이름만 아는 터", "", "QUIZ_FIND"))
    asyncio.run(generate_mission("탑골공원", _source()["overview"], "QUIZ_FIND"))

    bare, grounded = llm.prompts
    assert "이름 말고 확인된 자료가 없다" in bare
    assert "이름 말고 확인된 자료가 없다" not in grounded


# ── #9 페르소나 슬롯은 한 줄에 하나 ──────────────────────────────

def test_페르소나_슬롯이_한_줄에_하나씩_찍힌다():
    """`'  - '.join`으로 이어 붙어 세 슬롯이 한 줄로 나갔다(모델이 슬롯으로 못 읽는다)."""
    prompt = _prompt(node_name="탑골공원", stage="등장", context=_source()["overview"],
                     persona={"name": "석탑 도깨비", "motif": "탑·돌",
                              "archetype": "persona", "persona": "느긋하고 익살맞다."})

    assert "- 모티프: 탑·돌\n" in prompt
    assert "- 아키타입: persona\n" in prompt
    assert "  - " not in prompt                  # 한 줄에 두 슬롯이 붙지 않는다


# ── #10 술 제동은 kind가 아니라 원문으로 건다 ─────────────────────

def test_원문에_술이_있는_관광노드에도_제동이_붙는다():
    """식음 노드에만 걸려 있어 양조장·주막터 같은 관광 노드는 그대로 권했다."""
    prompt = _prompt(node_name="배다리 주막터", stage="등장", persona={"name": "옹기 도깨비"},
                     context="주막터에는 나그네에게 막걸리를 내주던 옛 우물이 남아 있다.")

    assert "술·주류가 적혀 있더라도" in prompt


def test_예술_미술은_술로_보지_않는다():
    """한 글자 '술'을 그냥 찾으면 인사동·미술관 원문이 전부 걸린다(오탐)."""
    assert not alcohol_in_source("인사동은 전통 예술과 미술 갤러리가 모인 거리다.")
    assert not alcohol_in_source("전통 공예 기술을 잇는 장인들이 있다.")
    assert alcohol_in_source("이 장어를 안주 삼아 복분자술을 먹어보는 것이 큰 희망이다.")
    assert alcohol_in_source("전통 막걸리를 빚는 양조장이 있다.")


def test_술_제동이_안_걸린_노드에는_규칙이_안_붙는다():
    """규칙을 늘 붙이면 모델이 없던 화제를 떠올린다 — 필요한 노드에만 붙인다."""
    prompt = _prompt(node_name="탑골공원", stage="등장", persona={"name": "석탑 도깨비"},
                     context=_source()["overview"])

    assert "술·주류가 적혀 있더라도" not in prompt


# ── #12 지령은 토큰 목록이 아니라 문장이다 ───────────────────────

def test_지령의_밑줄_표기를_공백으로_되돌린다(monkeypatch):
    """실 LLM 주행: 피날레 지령이 '1.망각귀_대마왕_조각 2.수호도깨비_반지'로 나갔다."""
    raw = ('{"villain_line":"곧 잊히리라.","guardian_line":"허허, 아니니라.",'
           '"order":"망각귀_대마왕_조각과 수호도깨비_반지를 ㄴ자_곡면에서 맞추어라.",'
           '"hints":["K-컬처_스크린 앞에 서거라.","잔디마당_쪽에서 보거라."]}')
    monkeypatch.setattr(node_content, "_llm", _CapturingLLM(raw))

    mission = asyncio.run(generate_mission("K-컬처 스크린", _source()["overview"],
                                           "DIALOGUE_COLLECT"))

    assert "_" not in mission["order"]
    assert mission["order"].startswith("망각귀 대마왕 조각과 수호도깨비 반지를")
    assert all("_" not in h for h in mission["hints"])


def test_미션_프롬프트가_지령_형식을_못박는다(monkeypatch):
    """사후 정리는 안전망이다 — 애초에 문장으로 쓰라고 요구한다(모든 미션 타입 공통)."""
    llm = _CapturingLLM('{"monster":"먹그림자","count":3,"boss":"흑묵","weakness":"불빛",'
                        '"find":"조각","order":"살펴라.","hints":["둘러보거라.","가까이 보거라."]}')
    monkeypatch.setattr(node_content, "_llm", llm)

    asyncio.run(generate_mission("탑골공원", _source()["overview"], "HUNT"))

    assert "번호 매기기·목록 기호·밑줄" in llm.prompts[0]


def test_밑줄_정리는_대사에는_걸지_않는다():
    """대사 경로의 clean_line은 그대로다 — 필터를 넓히면 되돌리기 어려운 삭제가 늘어난다."""
    assert clean_line("K-컬처_스크린 앞이니라.") == "K-컬처_스크린 앞이니라."


# ── #13 정답 가리기가 문장을 깨지 않는다 ────────────────────────
# 실 LLM 주행에서 H2가 "정답과 연결되는 대상와 연계된 예약 가능 상품을 확인하라"로 나갔다.
# 문장 가운데만 치환하니 조사가 남았고, 가린 뒤 판정해서 재생성도 안 돌았다.

def _leaky_mission(**overrides) -> dict:
    """정답('유료 스튜디오')이 힌트에 그대로 실린 미션 — 실 주행에서 나온 형태."""
    data = dict(_mission(
        type="QUIZ_FIND", q="프로필 촬영이 가능한 곳은?",
        options=["1층 체험 존", "유료 스튜디오", "3층 전시장", "피팅룸"],
        answer=1, wrong_hint="예약 방법을 다시 보거라.", find="황금 실타래",
        hints=["공식 홈페이지 안내란을 살펴보라.",
               "유료 스튜디오와 연계된 예약 가능 상품을 확인하라."]))
    data.pop("monster", None), data.pop("count", None)
    data.pop("boss", None), data.pop("weakness", None)
    data.update(overrides)
    return data


def _leaky_quest() -> dict:
    return _quest(_leaky_mission())


def test_유출된_힌트는_자리표시자가_아니라_문장으로_바뀐다():
    """'정답과 연결되는 대상와 연계된 …' — 조사가 남아 뜻도 문법도 깨졌다."""
    ladder = build_hint_ladder(_leaky_quest())

    joined = " ".join(ladder[k] for k in ("H1", "H2", "H3"))
    assert "유료 스튜디오" not in joined            # 정답은 여전히 가려진다
    assert "정답과 연결되는 대상" not in joined      # 자리표시자가 화면에 나가지 않는다
    assert ladder["H2"].endswith("거라.")           # 완전한 문장으로 대체됐다
    assert ladder["H1"] == "공식 홈페이지 안내란을 살펴보라."   # 안 샌 칸은 그대로 둔다


def test_폴백이_정답을_품으면_안전_문구로_떨어진다():
    """찾을 대상 이름이 곧 퀴즈 정답이면 폴백도 못 쓴다(폴백이 정답을 알려 준다)."""
    mission = _mission(type="QUIZ_FIND", q="무엇을 찾아야 하는가?",
                       options=["황금 실타래", "먹루", "돌비"], answer=0,
                       find="황금 실타래", wrong_hint="다시 살펴보거라.",
                       hints=["황금 실타래를 찾아보거라.", "황금 실타래 곁을 보거라."])
    ladder = build_hint_ladder(_quest(mission))

    joined = " ".join(ladder[k] for k in ("H1", "H2", "H3"))
    assert "황금 실타래" not in joined


def test_유출이_미션_재생성을_실제로_부른다(monkeypatch):
    """가린 뒤 판정하는 바람에 regen_mission 분기가 사실상 죽어 있었다."""
    regenerated: list[str] = []

    async def fake_generate_mission(name, overview, mtype, *, feedback=""):
        regenerated.append(feedback)
        return _leaky_mission(hints=["간판을 먼저 보거라.", "예약 안내판 곁을 보거라."])

    monkeypatch.setattr(qa_graph, "generate_mission", fake_generate_mission)

    # 계약 검사까지 통과하는 '조립을 마친' 노드로 돌린다(생성 경로와 같은 형태).
    leaky = enrich_quest(_leaky_quest(), _source(), motivations=["M1", "M7"])
    quest, flags = asyncio.run(qa_graph.run_qa_loop(leaky, _source(), {}))

    assert len(regenerated) == 1                       # 유출 → 미션/힌트만 1회 재생성
    assert "정답" in regenerated[0]                     # 무엇이 샜는지 알려주고 다시 쓰게 한다
    assert quest["hint_ladder"]["H1"] == "간판을 먼저 보거라."
    assert flags == []                                 # 다시 만든 힌트는 통과한다
