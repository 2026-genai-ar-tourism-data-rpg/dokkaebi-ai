# ============================================================
# [v1] 테스트: 앱 마법사 입력이 생성 파라미터까지 도달하는가
# pipeline: AI 백엔드 / 시나리오 (계약→생성 배선 회귀 방지)
# 구현(요약): 앱 3단계 입력이 ScenarioRequest에는 있는데 generate_basic_scenario까지
#            안 내려가면 화면만 바뀌고 코스는 그대로다 — 실제로 전달되는지 kwargs로 본다.
#            종로 고정 재생이 use_fixed_script 없이는 안 걸리는 것도 여기서 못 박는다
#            (#50 회귀: region만 보고 우회 → 무엇을 골라도 같은 코스).
# 구현일: 2026-08-18 | 작성: kys (explore-input-wiring/kys/v1)
# ============================================================
import asyncio

import app.scenario.generator as generator
from app.scenario.request import LatLng, ScenarioRequest


def _capture(monkeypatch) -> dict:
    """generate_basic_scenario 호출 kwargs를 가로챈다(실 TourAPI·LLM 없이 배선만 본다)."""
    captured: dict = {}

    async def fake_generate_basic(*args, **kwargs):
        captured.update(kwargs)
        return {"scenario_id": "scn_test", "title": "t", "region": "테스트", "node_sequence": []}

    monkeypatch.setattr(generator, "generate_basic_scenario", fake_generate_basic)
    return captured


def _req(**kw) -> ScenarioRequest:
    return ScenarioRequest(user_id="u", start=LatLng(lat=37.57, lng=126.98), **kw)


def test_duration이_노드수와_반경으로_내려간다(monkeypatch):
    captured = _capture(monkeypatch)
    asyncio.run(generator.generate_scenario(_req(duration="half", transport="walk")))
    assert captured["count"] == 6
    assert captured["radius_m"] == 3000        # 도보 기본 2000 × 1.5


def test_명시한_radius_m은_duration이_덮지_않는다(monkeypatch):
    captured = _capture(monkeypatch)
    asyncio.run(generator.generate_scenario(_req(duration="full", radius_m=1234)))
    assert captured["radius_m"] == 1234


def test_companion이_인원수로_내려간다(monkeypatch):
    captured = _capture(monkeypatch)
    scn = asyncio.run(generator.generate_scenario(_req(companion="family")))
    assert captured["headcount"] == 4          # 식음 예산 게이팅의 1인 예산 산출 근거
    assert scn["headcount"] == 4


def test_difficulty와_tags가_그대로_내려간다(monkeypatch):
    captured = _capture(monkeypatch)
    asyncio.run(generator.generate_scenario(_req(difficulty="hard", tags=["#고궁", "#역사"])))
    assert captured["difficulty"] == "hard"
    assert captured["tags"] == ["#고궁", "#역사"]


def test_입력이_응답에_에코된다(monkeypatch):
    """무엇을 골라 만든 코스인지 저장·검증할 수 있어야 한다."""
    _capture(monkeypatch)
    scn = asyncio.run(generator.generate_scenario(
        _req(duration="full", companion="couple", difficulty="easy", tags=["#카페"])
    ))
    assert scn["duration"] == "full"
    assert scn["companion"] == "couple"
    assert scn["difficulty"] == "easy"
    assert scn["tags"] == ["#카페"]


def test_종로도_기본은_동적생성이다(monkeypatch):
    """use_fixed_script 없이 region만 '종로'면 정답지가 아니라 동적 파이프라인."""
    captured = _capture(monkeypatch)
    scn = asyncio.run(generator.generate_scenario(_req(region="종로", duration="half")))
    assert captured, "종로라는 이유로 동적 생성을 건너뛰었다 — 커스터마이징이 전부 무시된다"
    assert scn["scenario_id"] == "scn_test"


def test_use_fixed_script면_정답지를_재생한다(monkeypatch):
    captured = _capture(monkeypatch)
    scn = asyncio.run(generator.generate_scenario(
        _req(region="종로", use_fixed_script=True, companion="friend")
    ))
    assert not captured, "정답지 재생인데 동적 생성이 돌았다"
    assert scn["scenario_id"] == "scn_종로_정답지"
    assert len(scn["node_sequence"]) == 7   # 프롤로그(안국역) + 조각 5개 + 피날레(광화문)
    assert scn["headcount"] == 2               # companion→인원수는 정답지에도 반영


def test_다른_지역은_use_fixed_script여도_동적생성이다(monkeypatch):
    """정답지는 종로 하나뿐 — 플래그가 켜져도 다른 지역까지 삼키면 안 된다."""
    captured = _capture(monkeypatch)
    asyncio.run(generator.generate_scenario(_req(region="강남", use_fixed_script=True)))
    assert captured
