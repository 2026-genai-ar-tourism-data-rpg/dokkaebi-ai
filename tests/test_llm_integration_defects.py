# ============================================================
# [v1] 실 LLM 연동 결함보고(2026-09-04) 회귀 스위트 — 결함 5건을 번호별로 잠근다
# pipeline: AI 백엔드 / 통합 (엔드포인트 계약 + 생성 경로. 네트워크·실 LLM 0)
# 구현(요약): Upstage solar-pro 실키 + TourAPI 실키로 앱이 실제로 보내는 요청을 돌렸을 때
#            나온 결함 5건이다. mock 프로바이더에서는 #1·#2가 재현되지 않았으므로,
#            여기서는 **실 LLM이 뱉은 실제 출력**을 가짜 LLM 응답으로 되먹여 재현한다.
#
#   #1 NPC 대사에 프롬프트 지시문이 그대로 출력   (치명, AI)      → core.wording
#   #2 QA 환각 판정이 100% 오탐 → #1의 원인        (치명, AI)      → node_schema·qa_graph
#   #3 마법사 입력 4개가 앱에서 전송되지 않음      (높음, 앱+서버) → AI 수용 계약만 잠근다
#   #4 식음 노드가 구조적으로 0개 → 예산 UI 무효   (높음, 설정)    → food_per_route
#   #5 대화 API에 branch·kind 미전송               (중간, 앱)      → AI 수용 계약만 잠근다
#
# #3·#5는 앱·서버 레포가 '보내는' 쪽을 고쳐야 한다(docs/handoff-app-server-contract-20260906.md).
# AI가 받을 준비가 되어 있다는 사실이 무너지면 그 핸드오프가 거짓이 되므로 여기서 못 박는다.
# 구현일: 2026-09-06 | 작성: pjh (agent-qa/pjh/v1)
# ============================================================
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.routes as routes
import app.scenario.generator as generator
import app.scenario.qa_graph as qa_graph
import app.tourapi.food as food
from app.core.wording import clean_line
from app.main import create_app
from app.pipeline.nodes.generate import generate as generate_node
from app.scenario.node_schema import run_qa

REPO_ROOT = Path(__file__).resolve().parents[1]

# 2026-09-04 실측 — 노드 4개 중 3개의 npc_dialogue에 프롬프트 지시문이 섞여 나왔다.
_LEAKED_DIALOGUE = (
    "허허, 이 자리가 바로 민영환 선생이 을사늑약의 치욕을 견디지 못해 "
    "순절로 목숨을 바친 곳이니라. 그 뜻을 헤아리지 않겠느냐?\n"
    "[규칙 준수]\n"
    "- 실제 소장 정보·유래·조형물(유서·단검) 등 실제 정보만 기술\n"
    '- "~니라" 어미와 감탄사 "허허" 적용\n'
    "- 3문장으로 소개 + 가벼운 질문 구성"
)
_LEAK_MARKERS = ("[규칙", "3문장", "감탄사", "어미와", "(※")

# 같은 점검에서 나온 '정상' 대사 4건 + 그 근거 원문. v3 판정은 이 4건을 전부 반려했다.
_MEASURED = [
    (
        "보신각터",
        "보신각은 조선시대 한양 도성의 종을 달아 두었던 종각이다. "
        "새벽과 저녁에 종을 쳐 도성 문을 여닫는 시각을 알렸다.",
        "여기가 바로 도성의 시간을 지키던 보신각터니라. 종소리 울리며 새벽을 알렸다는구먼. 허허.",
    ),
    (
        "민영환 자결터",
        "민영환 자결터는 을사늑약에 반대하여 자결한 충정공 민영환을 기리는 곳이다.",
        "허허, 이 자리가 바로 민영환 선생이 을사늑약의 치욕을 견디지 못해 "
        "순절로 목숨을 바친 곳이니라. 그 뜻을 헤아리지 않겠느냐?",
    ),
    (
        "탑골공원",
        "탑골공원은 1897년 조성된 서울 최초의 근대식 공원으로, 3·1운동이 시작된 곳이다. 팔각정이 남아 있다.",
        "이곳 탑골공원 팔각정은 삼일운동의 함성이 터져 나온 자리니라. 그 이야기를 듣고 싶으냐?",
    ),
    (
        "운현궁",
        "운현궁은 조선 후기의 역사적 장소이며 한옥 건축을 볼 수 있다. 흥선대원군이 머물던 곳이다.",
        "허허, 운현궁에서 한옥 건축의 흔적을 느껴보겠느냐? "
        "흥선대원군이 머물며 세워진 담장이 예까지 스며들었고, 가벼운 발걸음으로 살펴보거라.",
    ),
]


def _stub_nodes(monkeypatch) -> None:
    """실측 4개 장소를 TourAPI 후보로 세운다(네트워크 0)."""
    async def fake_nodes(*_a, **_k):
        return [
            {"node_id": f"tour_{i}", "name": name, "map_x": 126.98, "map_y": 37.570 + i * 0.002,
             "dist_m": 200 * (i + 1), "overview": overview, "addr1": "서울 종로구"}
            for i, (name, overview, _d) in enumerate(_MEASURED)
        ]
    monkeypatch.setattr(generator._tour, "location_based_list", fake_nodes)


def _stub_dialogue(monkeypatch, *, leak: bool = False) -> dict:
    """대사 LLM을 실측 출력으로 대체하고 호출 횟수·전달된 피드백을 기록한다."""
    calls: dict = {"n": 0, "feedback": []}
    by_name = {name: line for name, _ov, line in _MEASURED}

    async def fake_run_dialogue(node_id, stage, player_state, *, node_name="",
                                region_id="", qa_feedback="", npc=None):
        calls["n"] += 1
        calls["feedback"].append(qa_feedback)
        text = _LEAKED_DIALOGUE if leak else by_name.get(node_name, "허허, 흔적을 살펴보거라.")
        return text, False

    monkeypatch.setattr(generator, "run_dialogue", fake_run_dialogue)
    monkeypatch.setattr(qa_graph, "run_dialogue", fake_run_dialogue)
    return calls


def _generate(**overrides):
    kwargs = dict(map_x=126.9856, map_y=37.5703, region="종로", radius_m=2000, count=4,
                  with_dialogue=True, with_content=False, no_meals=True)
    kwargs.update(overrides)
    return asyncio.run(generator.generate_basic_scenario(**kwargs))


# ══ 결함 #1 — 도깨비가 대사 대신 프롬프트 규칙을 읽어 준다 ═══════════════════
#
# 앱은 npc_dialogue를 QuestNode.npcDialogue로 그대로 그린다. 출력 정리 함수를
# 지나온 값에는 지시문이 남아 있으면 안 된다. (실측 4건 자체는 tests/core/test_wording.py)


def test_결함1_LLM_출력_정리_노드가_메타블록을_걷어낸다():
    """clean_line은 파이프라인 generate 노드에서 걸린다 — 여기가 캐시·앱으로 나가는 마지막 관문."""
    import app.pipeline.nodes.generate as gen_node

    class _FakeLLM:
        async def generate(self, _prompt, **_kw):
            return _LEAKED_DIALOGUE

    original, gen_node._llm = gen_node._llm, _FakeLLM()
    try:
        out = asyncio.run(generate_node({"prompt": "..."}))["response"]
    finally:
        gen_node._llm = original

    assert not any(m in out for m in _LEAK_MARKERS), out
    assert out.startswith("허허, 이 자리가 바로 민영환 선생이")


def test_결함1_유출된_대사가_노드에_실려도_생성_경로에서_정리된다(monkeypatch):
    """캐시에 굳은 옛 대사처럼 정리 전 값이 들어와도 앱까지 나가지 않게 한다."""
    _stub_nodes(monkeypatch)
    _stub_dialogue(monkeypatch, leak=True)

    scn = _generate()

    for node in scn["node_sequence"]:
        cleaned = clean_line(node["npc_dialogue"])
        assert not any(m in cleaned for m in _LEAK_MARKERS), node["npc_dialogue"]


# ══ 결함 #2 — QA 환각 판정의 정밀도가 0/35였다 ═══════════════════════════════


@pytest.mark.parametrize("name,overview,dialogue", _MEASURED, ids=[m[0] for m in _MEASURED])
def test_결함2_실측_정상대사는_환각으로_판정되지_않는다(name, overview, dialogue):
    """v3은 이 4건을 전부 반려했다(참양성 0건). 표기 차이 '삼일운동↔3·1운동' 포함."""
    qa = run_qa({"npc_dialogue": dialogue, "quiz": {}, "hint_ladder": {}}, {"name": name, "overview": overview})
    assert qa["hallucination_flag"] is False, qa["unsupported_tokens"]


def test_결함2_생성_경로의_대사_호출이_노드당_1회로_돌아온다(monkeypatch):
    """실측: 노드 4개 × 재생성 2회 = 12회. 게이트를 떼면 4회로 돌아온다."""
    _stub_nodes(monkeypatch)
    calls = _stub_dialogue(monkeypatch)

    scn = _generate()

    assert len(scn["node_sequence"]) == 4
    assert calls["n"] == 4                       # 12회가 아니다
    assert scn["qa_flags"] == []                 # 품질 경고 4건이 매번 따라 나오지 않는다
    assert calls["feedback"] == [""] * 4         # 재생성 지시문이 실린 호출 자체가 없다


def test_결함2_진짜_환각은_경고로_남는다(monkeypatch):
    """게이트에서 뗐다고 판정을 버린 것은 아니다 — 재생성 없이 사유만 남긴다."""
    _stub_nodes(monkeypatch)

    async def fake_run_dialogue(node_id, stage, player_state, *, node_name="",
                                region_id="", qa_feedback="", npc=None):
        return "이곳에는 1919년 세워진 첨성대와 석굴암이 있느니라, 허허.", False

    monkeypatch.setattr(generator, "run_dialogue", fake_run_dialogue)
    monkeypatch.setattr(qa_graph, "run_dialogue", fake_run_dialogue)

    scn = _generate()

    assert scn["qa_flags"], "근거 밖 주장이 있으면 경고는 남아야 한다"
    assert all("경고" in f and "재생성하지 않음" in f for f in scn["qa_flags"])
    # 경고일 뿐이므로 대사는 그대로 나간다(결과를 죽이지 않는다).
    assert all("첨성대" in n["npc_dialogue"] for n in scn["node_sequence"])


def test_결함2_판정_기준은_검증가능한_주장뿐이다():
    """서술어·문체어는 후보에도 오르지 않는다 — 오탐 35건의 실제 구성."""
    overview = "운현궁은 조선 후기의 역사적 장소이며 한옥 건축을 볼 수 있다."
    # 실측 오탐 목록에서 그대로 가져온 용언 활용형·문체어만으로 된 대사.
    dialogue = ("허허, 운현궁에서 세워진 흔적을 느껴보겠느냐? 끝내주니 가벼운 발걸음으로 "
                "복원했으며 스며들었고 싶으냐 터이니 살펴보거라.")
    qa = run_qa({"npc_dialogue": dialogue, "quiz": {}, "hint_ladder": {}}, {"overview": overview})
    assert qa["unsupported_tokens"] == []
    assert qa["hallucination_flag"] is False


# ══ 결함 #3 — 마법사 입력 4개가 앱에서 전송되지 않는다 ════════════════════════
#
# 고칠 곳은 앱·서버다. 여기서는 **AI가 받을 준비가 되어 있다**는 것만 잠근다 —
# 이게 무너지면 핸드오프 문서(docs/handoff-app-server-contract-20260906.md)가 거짓이 된다.

_WIZARD_INPUT = {
    "user_id": "tester",
    "start": {"lat": 37.5703, "lng": 126.9856},
    "transport": "walk",
    "budget": 30000,
    "no_meals": False,
    # ↓ 앱이 "서버 미지원 필드"라며 로컬에만 들고 있던 것들
    "duration": "half",
    "companion": "family",
    "difficulty": "hard",
    "tags": ["역사", "고궁"],
    "headcount": 4,
    "use_fixed_script": False,
}


def _capture_request(monkeypatch) -> dict:
    """엔드포인트가 생성기로 넘기는 ScenarioRequest를 가로챈다."""
    seen: dict = {}

    async def fake_generate_scenario(req):
        seen["req"] = req
        return {
            "scenario_id": "scn_종로_test", "title": "종로의 기억석", "region": "종로",
            "type": "custom", "node_sequence": [], "stone_total": 0, "anchor_node_id": None,
            "duration": req.duration, "companion": req.companion, "difficulty": req.difficulty,
            "tags": list(req.tags), "headcount": req.headcount, "transport": req.transport,
            "budget": req.budget,
        }

    monkeypatch.setattr(routes, "generate_scenario", fake_generate_scenario)
    return seen


def test_결함3_마법사_입력_전부가_생성기까지_도달한다(monkeypatch):
    seen = _capture_request(monkeypatch)
    resp = TestClient(create_app()).post("/v1/scenarios", json=_WIZARD_INPUT)

    assert resp.status_code == 200
    req = seen["req"]
    assert req.duration == "half"
    assert req.companion == "family"
    assert req.difficulty == "hard"
    assert req.tags == ["역사", "고궁"]
    assert req.headcount == 4
    assert req.use_fixed_script is False


def test_결함3_응답이_요청값을_에코해_잘림을_드러낸다(monkeypatch):
    """서버 ValidationPipe(whitelist)가 필드를 삼켰는지 앱이 확인할 수 있는 유일한 창구."""
    _capture_request(monkeypatch)
    body = TestClient(create_app()).post("/v1/scenarios", json=_WIZARD_INPUT).json()

    assert body["duration"] == "half"
    assert body["companion"] == "family"
    assert body["difficulty"] == "hard"
    assert body["tags"] == ["역사", "고궁"]
    assert body["headcount"] == 4


def test_결함3_필드를_안_보내던_옛_앱도_그대로_동작한다(monkeypatch):
    """하위호환 — 앱이 아직 안 고쳐졌어도 500이 나면 안 된다."""
    seen = _capture_request(monkeypatch)
    old_body = {"user_id": "tester", "start": {"lat": 37.5703, "lng": 126.9856},
                "transport": "walk", "budget": 30000, "no_meals": False}
    resp = TestClient(create_app()).post("/v1/scenarios", json=old_body)

    assert resp.status_code == 200
    req = seen["req"]
    assert (req.duration, req.companion, req.difficulty, req.tags) == ("2h", "solo", "normal", [])


def test_결함3_companion이_예산_게이팅_인원수로_변환된다():
    """연쇄 결함 — headcount가 없으면 1인 기준으로 예산이 계산된다."""
    from app.scenario.preference import headcount_for

    assert headcount_for("family", 1) == 4
    assert headcount_for("couple", 1) == 2
    assert headcount_for("solo", 1) == 1
    assert headcount_for("family", 3) == 3      # 앱이 직접 보낸 값이 우선


# ══ 결함 #4 — 식음 노드가 구조적으로 0개다 ═══════════════════════════════════

_FOOD_CANDIDATES = [
    {"node_id": "food_1", "tour_content_id": None, "name": "종로 국밥", "kind": "food",
     "map_x": 126.981, "map_y": 37.572, "addr1": None, "cat3": None,
     "price_band": 1, "price_band_label": "1만원대", "price_source": "test", "source": "test"},
    {"node_id": "cafe_1", "tour_content_id": None, "name": "익선동 다방", "kind": "cafe",
     "map_x": 126.989, "map_y": 37.574, "addr1": None, "cat3": None,
     "price_band": 1, "price_band_label": "1만원대", "price_source": "test", "source": "test"},
]


def _stub_food(monkeypatch) -> None:
    async def fake_nearby(*_a, **_k):
        return [dict(c) for c in _FOOD_CANDIDATES]
    monkeypatch.setattr(food, "nearby_food_async", fake_nearby)


def _food_nodes(scn: dict) -> list[dict]:
    return [n for n in scn["node_sequence"] if n.get("kind") in ("food", "cafe")]


def test_결함4_설정이_켜지면_식음_노드가_생긴다(monkeypatch):
    """실측: no_meals=false·budget=30000으로 생성해도 식당·카페가 0개였다."""
    _stub_nodes(monkeypatch)
    _stub_dialogue(monkeypatch)
    _stub_food(monkeypatch)
    monkeypatch.setattr(generator.get_settings(), "scenario_food_per_route", 2)

    scn = _generate(no_meals=False, budget=30000, headcount=2)

    assert _food_nodes(scn), "식음 노드가 하나도 없다 — 예산·식음 UI가 무효가 된다"


def test_결함4_기본값_0이면_식음이_0개다_회귀_상태_기록(monkeypatch):
    """보고서가 잡은 그 상태 그대로 — 설정을 안 켜면 no_meals=false가 무의미하다."""
    _stub_nodes(monkeypatch)
    _stub_dialogue(monkeypatch)
    _stub_food(monkeypatch)
    monkeypatch.setattr(generator.get_settings(), "scenario_food_per_route", 0)

    scn = _generate(no_meals=False, budget=30000)

    assert _food_nodes(scn) == []


def test_결함4_no_meals면_설정이_켜져도_식음이_없다(monkeypatch):
    """'밥 안 먹음'은 설정보다 우선한다."""
    _stub_nodes(monkeypatch)
    _stub_dialogue(monkeypatch)
    _stub_food(monkeypatch)
    monkeypatch.setattr(generator.get_settings(), "scenario_food_per_route", 2)

    scn = _generate(no_meals=True, budget=30000)

    assert _food_nodes(scn) == []


def test_결함4_식음_노드는_기억석_조각을_받지_않는다(monkeypatch):
    """조각 수는 관광 노드만 센다 — 식음이 들어와도 계약이 흔들리면 안 된다."""
    _stub_nodes(monkeypatch)
    _stub_dialogue(monkeypatch)
    _stub_food(monkeypatch)
    monkeypatch.setattr(generator.get_settings(), "scenario_food_per_route", 2)

    scn = _generate(no_meals=False, budget=30000)

    assert all(n.get("fragment_id") in (None, "") for n in _food_nodes(scn))
    assert scn["stone_total"] == len(scn["node_sequence"]) - len(_food_nodes(scn))


def test_결함4_env_example에_항목이_있다():
    """실측: .env.example에 이 항목이 없어 새로 받은 사람은 0인 줄도 몰랐다."""
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "DOKKAEBI_SCENARIO_FOOD_PER_ROUTE" in example


# ══ 결함 #5 — 대화 API에 갈림길·노드종류 정보가 빠져 있다 ═════════════════════
#
# 고칠 곳은 앱이다. AI가 받는 쪽이 열려 있음을 잠근다.

_BRANCH = {
    "prompt": "어느 길로 가겠느냐?",
    "options": [
        {"choice_id": "main", "label": "큰길", "next_node_id": "tour_124"},
        {"choice_id": "b1", "label": "샛길", "next_node_id": "tour_130"},
    ],
}


def _capture_turn(monkeypatch) -> dict:
    seen: dict = {}

    async def fake_run_branching(**kwargs):
        seen.update(kwargs)
        return {"response": "허허.", "choices": [], "grants": [], "done": False}

    monkeypatch.setattr(routes, "run_branching", fake_run_branching)
    return seen


def test_결함5_branch와_kind가_대화_서비스까지_도달한다(monkeypatch):
    """AI는 시나리오를 들고 있지 않은 무상태 서비스다 — 앱이 실어 줘야 분기를 안다."""
    seen = _capture_turn(monkeypatch)
    resp = TestClient(create_app()).post("/v1/dialogue/turn", json={
        "node_id": "tour_1", "node_name": "보신각터",
        "region_id": "종로", "kind": "food",
        "player_state": {"progress": 2, "required": 4},
        "branch": _BRANCH,
    })

    assert resp.status_code == 200
    assert seen["kind"] == "food"
    assert seen["region_id"] == "종로"
    assert seen["player_state"] == {"progress": 2, "required": 4}
    assert seen["branch"]["options"][1]["choice_id"] == "b1"


def test_결함5_안_보내던_옛_앱은_기본값으로_동작한다(monkeypatch):
    """지금 상태(잠복) — 200이 나지만 분기·식음 정보가 비어 있다."""
    seen = _capture_turn(monkeypatch)
    resp = TestClient(create_app()).post("/v1/dialogue/turn", json={
        "node_id": "tour_1", "node_name": "보신각터",
    })

    assert resp.status_code == 200
    assert seen["kind"] == "spot"      # 식음 노드에서도 조각 의뢰 대사가 나가는 이유
    assert seen["branch"] is None      # with_branching을 켜는 순간 갈림길이 깨지는 이유
    assert seen["region_id"] == ""

# kind가 실제로 대사를 바꾸는지(식음 노드에서 조각을 의뢰하지 않는지)는
# tests/services/test_branching_service.py::test_food_node_never_asks_for_a_stone이 잠근다.
