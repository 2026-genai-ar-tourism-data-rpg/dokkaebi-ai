# ============================================================
# [v1] 테스트: A1 생성 QA 대응 루프 + 미션 생성 실패 재시도
# pipeline: AI 백엔드 / 시나리오 (생성 품질 회귀 방지, 네트워크·실 LLM 0)
# 커버: ① QA 최초 실패 → 1회 재생성 → PASS(재생성 1회·피드백 전달·qa_flags 없음)
#       ② QA 계속 실패 → 재생성 상한 2회 · QA 검사 3회 · qa_flags 생성
#       ③ 실패 원인별 재생성 대상 분리(정답유출=미션 / 말투·환각=대사)
#       ④ 계약 위반은 LLM 재생성 없이 flag
#       ⑤ 미션 생성 실패 → 1회 재시도 성공(호출 2회·제네릭 폴백 미사용)
#       ⑥ 미션 재시도까지 실패 → 기존 제네릭 폴백 + qa_flags 기록
#       ⑦ 응답 DTO qa_flags 기본값 []
# 구현일: 2026-09-04 | 작성: pjh (agent-qa/pjh/v1)
# ============================================================
import asyncio

import pytest
from fastapi.testclient import TestClient

import app.scenario.generator as generator
import app.scenario.node_content as node_content
import app.scenario.qa_graph as qa_graph
from app.main import create_app
from app.scenario.node_schema import enrich_quest


def _source(**overrides) -> dict:
    data = {
        "node_id": "tour_test",
        "name": "운현궁",
        "content_type_id": 12,
        "cat1": "A02",
        "overview": "운현궁은 조선 후기의 역사적 장소이며 한옥 건축을 볼 수 있다.",
    }
    data.update(overrides)
    return data


def _quest() -> dict:
    """generator._build_quest가 만드는 것과 같은 형태의 (enrich를 마친) 관광 퀘스트."""
    mission = {
        "type": "QUIZ_FIND",
        "order": "운현궁의 현판을 살펴 파편을 찾아라.",
        "hints": ["주변을 둘러보거라.", "현판 가까이 보거라."],
        "q": "운현궁은 어느 시대의 장소인가?",
        "options": ["조선 후기", "고려", "삼국", "근대"],
        "answer": 0,
        "wrong_hint": "다시 살펴보거라.",
        "find": "기억석 파편",
    }
    quest = {
        "order": 0,
        "node_id": "tour_test",
        "name": "운현궁",
        "kind": "spot",
        "mission": mission,
        "quiz": node_content.to_quiz(mission),
        "objective": {"order": mission["order"], "hints": mission["hints"]},
        "trigger_radius_m": 100,
        "stone_no": 1,
        "fragment_id": "종로_stone_1of1",
        "npc_dialogue": "허허, 이곳의 흔적을 살펴보거라.",
        "is_finale": False,
    }
    return enrich_quest(quest, _source())


def _qa_result(*, answer_leak=False, tone_ok=True, hallucination=False, contract_ok=True) -> dict:
    """run_qa가 돌려주는 것과 같은 형태의 판정 결과(테스트가 결정적으로 조종)."""
    return {
        "answer_leak": answer_leak,
        "tone_ok": tone_ok,
        "hallucination_flag": hallucination,
        "unsupported_tokens": ["우주선", "공룡화석", "피라미드"] if hallucination else [],
        "contract_ok": contract_ok,
    }


def _patch_regen(monkeypatch) -> dict:
    """재생성 LLM 호출을 가짜로 바꾸고 호출 기록(전달된 피드백)을 돌려준다."""
    calls: dict = {"dialogue": [], "mission": []}

    async def fake_run_dialogue(node_id, stage, player_state, *, node_name="",
                                region_id="", qa_feedback=""):
        calls["dialogue"].append(qa_feedback)
        return "허허, 다시 쓴 대사니라.", False

    async def fake_generate_mission(name, overview, mtype, *, feedback=""):
        calls["mission"].append(feedback)
        return {
            "type": mtype, "order": "다시 쓴 지령", "hints": ["다시 쓴 힌트"],
            "q": "운현궁은 어느 시대의 장소인가?", "options": ["조선 후기", "고려", "삼국", "근대"],
            "answer": 0, "wrong_hint": "다시 살펴보거라.", "find": "기억석 파편",
        }

    monkeypatch.setattr(qa_graph, "run_dialogue", fake_run_dialogue)
    monkeypatch.setattr(qa_graph, "generate_mission", fake_generate_mission)
    return calls


# ── ①② A1 QA 루프 — 재생성 횟수·피드백·qa_flags ────────────────────────


def test_qa_최초_실패면_1회_재생성하고_통과한다(monkeypatch):
    """예전엔 경고 로그만 남기고 그대로 나갔다 — 이제 문제 출력만 다시 만든다."""
    calls = _patch_regen(monkeypatch)
    checks = {"n": 0}

    def fake_run_qa(node, source):
        checks["n"] += 1
        return _qa_result(tone_ok=checks["n"] > 1)      # 1회차만 말투 실패

    monkeypatch.setattr(qa_graph, "run_qa", fake_run_qa)

    quest, flags = asyncio.run(qa_graph.run_qa_loop(_quest(), _source()))

    assert checks["n"] == 2                              # 최초 검사 + 재생성 후 재검사
    assert len(calls["dialogue"]) == 1                   # 재생성은 정확히 1회
    assert "도깨비" in calls["dialogue"][0]               # 실패 사유가 다음 호출에 전달됐다
    assert quest["npc_dialogue"] == "허허, 다시 쓴 대사니라."
    assert flags == []                                   # 해결됐으면 경고를 남기지 않는다


def test_qa가_계속_실패하면_재생성은_2회까지고_사유를_남긴다(monkeypatch):
    calls = _patch_regen(monkeypatch)
    checks = {"n": 0}

    def fake_run_qa(node, source):
        checks["n"] += 1
        return _qa_result(tone_ok=False)                 # 몇 번을 다시 써도 실패

    monkeypatch.setattr(qa_graph, "run_qa", fake_run_qa)

    _quest_out, flags = asyncio.run(qa_graph.run_qa_loop(_quest(), _source()))

    assert len(calls["dialogue"]) == 2                   # 재생성 상한(기본 2)
    assert checks["n"] == 3                              # 최초 1 + 재생성 2회 뒤 검사 2 = 3
    assert flags and any("말투" in f for f in flags)      # 결과를 죽이지 않고 사유만 남긴다
    assert any("운현궁" in f for f in flags)


def test_재생성_상한이_설정으로_조절된다(monkeypatch):
    """scenario_qa_max_regen=0이면 재생성 없이 곧장 사유만 남긴다(비용 탈출구)."""
    calls = _patch_regen(monkeypatch)
    monkeypatch.setattr(qa_graph, "run_qa", lambda node, source: _qa_result(tone_ok=False))

    settings = generator.get_settings()
    monkeypatch.setattr(settings, "scenario_qa_max_regen", 0)

    _quest_out, flags = asyncio.run(qa_graph.run_qa_loop(_quest(), _source()))

    assert calls["dialogue"] == []
    assert flags


# ── ③④ 실패 원인별 재생성 대상 ─────────────────────────────────────────


def test_정답유출이면_미션만_재생성한다(monkeypatch):
    """정답이 힌트로 샌 것은 미션/힌트 문제다 — 멀쩡한 대사를 다시 만들지 않는다."""
    calls = _patch_regen(monkeypatch)
    checks = {"n": 0}

    def fake_run_qa(node, source):
        checks["n"] += 1
        return _qa_result(answer_leak=checks["n"] == 1)

    monkeypatch.setattr(qa_graph, "run_qa", fake_run_qa)

    quest, flags = asyncio.run(qa_graph.run_qa_loop(_quest(), _source()))

    assert len(calls["mission"]) == 1
    assert calls["dialogue"] == []                       # 대사는 건드리지 않는다
    assert "정답" in calls["mission"][0]                  # 유출된 정답을 알려주고 다시 쓰게 한다
    assert quest["mission"]["order"] == "다시 쓴 지령"
    assert quest["hint_ladder"]["H1"] == "다시 쓴 힌트"    # 힌트 사다리도 다시 컴파일된다
    assert flags == []


def test_말투_환각이면_대사만_재생성한다(monkeypatch):
    calls = _patch_regen(monkeypatch)
    checks = {"n": 0}

    def fake_run_qa(node, source):
        checks["n"] += 1
        return _qa_result(hallucination=checks["n"] == 1)

    monkeypatch.setattr(qa_graph, "run_qa", fake_run_qa)

    quest, flags = asyncio.run(qa_graph.run_qa_loop(_quest(), _source()))

    assert len(calls["dialogue"]) == 1
    assert calls["mission"] == []                        # 미션은 건드리지 않는다
    assert "우주선" in calls["dialogue"][0]               # 근거 밖 표현을 짚어 준다
    assert quest["mission"]["order"] == "운현궁의 현판을 살펴 파편을 찾아라."
    assert flags == []


def test_계약위반은_재생성_없이_flag한다(monkeypatch):
    """스키마 결함은 LLM이 다시 써도 안 고쳐진다 — 무의미한 호출을 하지 않는다."""
    calls = _patch_regen(monkeypatch)
    checks = {"n": 0}

    def fake_run_qa(node, source):
        checks["n"] += 1
        return _qa_result(contract_ok=False)

    monkeypatch.setattr(qa_graph, "run_qa", fake_run_qa)

    _quest_out, flags = asyncio.run(qa_graph.run_qa_loop(_quest(), _source()))

    assert checks["n"] == 1
    assert calls["dialogue"] == [] and calls["mission"] == []
    assert any("계약 위반" in f for f in flags)


# ── ⑤⑥ 미션 생성 실패 재시도 ──────────────────────────────────────────

_META = {"is_food": False, "is_finale": False, "stone_no": 1, "stone_index": 0, "stone_total": 1}
_GENERIC_ORDER = "운현궁에서 기억석 조각을 찾아라."     # node_content._normalize의 제네릭 폴백 지령


def _patch_llm(monkeypatch, replies: list[str]) -> list[str]:
    """미션 생성 LLM 응답을 순서대로 돌려주고 프롬프트를 기록한다(실 API 호출 0)."""
    prompts: list[str] = []

    async def fake_generate(prompt, **kwargs):
        prompts.append(prompt)
        return replies[min(len(prompts) - 1, len(replies) - 1)]

    monkeypatch.setattr(node_content._llm, "generate", fake_generate)
    return prompts


def test_미션_생성_최초_실패면_1회_재시도해_성공한다(monkeypatch):
    prompts = _patch_llm(monkeypatch, [
        "JSON이 아닌 응답이니라",                                     # 1회차: 파싱 실패
        '{"order":"실제로 생성된 지령","hints":["실제 힌트"]}',        # 2회차: 성공
    ])
    flags: list[str] = []

    mission = asyncio.run(generator._content_for(_source(), _META, ["M1"], flags))

    assert len(prompts) == 2                             # 최초 + 재시도 1회
    assert "[재작성 지시]" in prompts[1]                  # 재시도에는 실패 사유를 싣는다
    assert mission["order"] == "실제로 생성된 지령"        # 제네릭 폴백이 아니다
    assert flags == []


def test_미션_재시도까지_실패하면_제네릭_폴백하고_사유를_남긴다(monkeypatch):
    prompts = _patch_llm(monkeypatch, ["JSON이 아닌 응답이니라"])
    flags: list[str] = []

    mission = asyncio.run(generator._content_for(_source(), _META, ["M1"], flags))

    assert len(prompts) == 2                             # 최초 + 재시도 1회로 그친다
    assert mission["order"] == _GENERIC_ORDER            # 기존 제네릭 폴백은 그대로 살아 있다
    assert mission["hints"]                              # 폴백도 항상 힌트를 보장한다
    assert flags == ["운현궁: 미션 생성 실패 → 제네릭 미션 폴백"]


def test_미션_재시도_횟수가_설정으로_조절된다(monkeypatch):
    prompts = _patch_llm(monkeypatch, ["JSON이 아닌 응답이니라"])
    monkeypatch.setattr(generator.get_settings(), "scenario_mission_max_retries", 0)
    flags: list[str] = []

    asyncio.run(generator._content_for(_source(), _META, ["M1"], flags))

    assert len(prompts) == 1                             # 재시도 없음
    assert flags == ["운현궁: 미션 생성 실패 → 제네릭 미션 폴백"]


def test_LLM_호출_자체가_실패해도_재시도_후_폴백한다(monkeypatch):
    """LLMClient의 429 백오프가 소진돼 올라온 실패도 같은 경로로 다룬다."""
    calls = {"n": 0}

    async def boom(prompt, **kwargs):
        calls["n"] += 1
        raise RuntimeError("LLM rate limit 재시도 소진")

    monkeypatch.setattr(node_content._llm, "generate", boom)
    flags: list[str] = []

    mission = asyncio.run(generator._content_for(_source(), _META, ["M1"], flags))

    assert calls["n"] == 2
    assert mission["order"] == _GENERIC_ORDER
    assert flags == ["운현궁: 미션 생성 실패 → 제네릭 미션 폴백"]


def test_식음노드는_미션도_플래그도_없다(monkeypatch):
    """식음 노드는 기억석 미션 대상이 아니다 — 기존 동작 유지."""
    _patch_llm(monkeypatch, ["JSON이 아닌 응답이니라"])
    flags: list[str] = []
    meta = dict(_META, is_food=True)

    assert asyncio.run(generator._content_for(_source(), meta, ["M6"], flags)) is None
    assert flags == []


# ── ⑦ 응답 DTO ────────────────────────────────────────────────────────

_FAKE_SCENARIO = {
    "scenario_id": "scn_종로_test",
    "title": "종로의 기억석 — 1조각 코스",
    "region": "종로",
    "type": "custom",
    "node_sequence": [],
    "stone_total": 1,
    "anchor_node_id": "tour_1",
}

_REQUEST = {"user_id": "tester", "start": {"lat": 37.5796, "lng": 126.9770}}


def _client(monkeypatch, scenario: dict) -> TestClient:
    import app.api.routes as routes

    async def _fake(_req):
        return dict(scenario)

    monkeypatch.setattr(routes, "generate_scenario", _fake)
    return TestClient(create_app())


def test_정상_시나리오_응답의_qa_flags는_빈배열이다(monkeypatch):
    """생성기가 qa_flags를 안 채워도(정답지 재생 등) 응답은 빈 배열 — 하위호환."""
    client = _client(monkeypatch, _FAKE_SCENARIO)
    body = client.post("/v1/scenarios", json=_REQUEST).json()
    assert body["qa_flags"] == []


def test_생성이_남긴_qa_flags가_응답으로_나간다(monkeypatch):
    flags = ["운현궁: 미션 생성 실패 → 제네릭 미션 폴백"]
    client = _client(monkeypatch, dict(_FAKE_SCENARIO, qa_flags=flags))
    body = client.post("/v1/scenarios", json=_REQUEST).json()
    assert body["qa_flags"] == flags


@pytest.mark.parametrize("with_content", [True, False])
def test_생성기가_항상_qa_flags를_반환한다(monkeypatch, with_content):
    """mock provider(키 없음)로도 코스는 만들어지고 qa_flags 키는 항상 존재한다."""
    async def fake_nodes(*args, **kwargs):
        return [
            {"node_id": "tour_1", "name": "운현궁", "map_x": 126.985, "map_y": 37.574,
             "dist_m": 100, "overview": "운현궁은 조선 후기의 역사적 장소다.", "addr1": "서울 종로구"},
            {"node_id": "tour_2", "name": "경복궁", "map_x": 126.977, "map_y": 37.579,
             "dist_m": 300, "overview": "경복궁은 조선의 법궁이다.", "addr1": "서울 종로구"},
        ]

    monkeypatch.setattr(generator._tour, "location_based_list", fake_nodes)
    scn = asyncio.run(generator.generate_basic_scenario(
        126.977, 37.579, region="종로", radius_m=2000, count=2,
        with_dialogue=False, with_content=with_content, no_meals=True,
    ))
    assert isinstance(scn["qa_flags"], list)
