# ============================================================
# [v1] 테스트: 코스 오프닝 프롤로그 생성
# pipeline: AI 백엔드 / 시나리오 (생성 회귀 방지, 네트워크·실 LLM 0)
# 커버: ① 정상 생성 — LLM이 "1".."20" 키를 다 채우면 24줄(beat 포함)로 정확히 병합된다
#       ② 여벌 키가 섞여 와도(#21 등) 1~20번만 있으면 그대로 쓴다(실측 회귀 — 처음엔
#          배열 길이만 요구했더니 LLM이 하나 더 얹어 보내 멀쩡한 결과를 통째로 버렸다)
#       ③ 필수 키 누락·비JSON — 지역명만 반영한 고정 대본으로 폴백,
#          {name} 플레이스홀더는 그대로 남는다
# 구현일: 2026-09-04 | 작성: Claude (prologue-story-gen/claude/v1)
# ============================================================
import asyncio
import json

from app.scenario import prologue_content
from app.scenario.prologue_content import _MAX_TOKENS, _SKELETON, _TEXT_SLOTS, fallback_prologue, generate_prologue


def _patch_llm(monkeypatch, reply: str) -> list[dict]:
    """LLM 응답을 고정하고 실제로 전달된 kwargs(max_tokens 등)를 기록한다."""
    calls: list[dict] = []

    async def fake_generate(prompt, **kwargs):
        calls.append(kwargs)
        return reply

    monkeypatch.setattr(prologue_content._llm, "generate", fake_generate)
    return calls


def _keyed(texts: list[str], extra: dict | None = None) -> str:
    lines = {str(i + 1): t for i, t in enumerate(texts)}
    if extra:
        lines.update(extra)
    return json.dumps({"lines": lines})


def test_정상_생성이면_20개_슬롯을_스켈레톤_순서대로_채운다(monkeypatch):
    texts = [f"대사{i}" for i in range(len(_TEXT_SLOTS))]
    calls = _patch_llm(monkeypatch, _keyed(texts))

    lines = asyncio.run(generate_prologue("강남구", {"name": "봉은사"}))

    # 실측 회귀: 기본 max_tokens(512)로는 20줄 JSON이 중간에 잘려 매번 폴백했다 —
    # 이 호출은 늘린 값을 실제로 넘겨야 한다.
    assert calls[0]["max_tokens"] == _MAX_TOKENS
    assert len(lines) == len(_SKELETON) == 24
    # beat 슬롯은 텍스트 없이 원래 위치·이름 그대로
    beat_positions = [i for i, s in enumerate(_SKELETON) if s["speaker"] == "beat"]
    for i in beat_positions:
        assert lines[i]["speaker"] == "beat"
        assert lines[i]["text"] == ""
        assert lines[i]["beat"] == _SKELETON[i]["beat"]
    # 텍스트 슬롯은 LLM이 준 문장을 순서대로, 화자는 스켈레톤 그대로
    text_positions = [i for i, s in enumerate(_SKELETON) if s["speaker"] != "beat"]
    for slot_no, i in enumerate(text_positions):
        assert lines[i]["speaker"] == _SKELETON[i]["speaker"]
        assert lines[i]["text"] == texts[slot_no]
        assert lines[i]["beat"] is None


def test_여벌_키가_섞여도_1번부터_n번까지만_있으면_통과한다(monkeypatch):
    """실측 회귀: 20개를 요청했는데 LLM이 21번째 키를 더 얹어 보낸 사례."""
    texts = [f"대사{i}" for i in range(len(_TEXT_SLOTS))]
    _patch_llm(monkeypatch, _keyed(texts, extra={str(len(_TEXT_SLOTS) + 1): "여벌 대사"}))

    lines = asyncio.run(generate_prologue("제물포구", {"name": "백운산전망대"}))

    assert lines != fallback_prologue("제물포구", "백운산전망대")   # 폴백이 아니라 LLM 결과여야 한다
    text_positions = [i for i, s in enumerate(_SKELETON) if s["speaker"] != "beat"]
    assert lines[text_positions[0]]["text"] == "대사0"


def test_필수_키가_누락되면_지역명_치환_폴백으로_24줄을_보장한다(monkeypatch):
    _patch_llm(monkeypatch, json.dumps({"lines": {"1": "딱 하나만 왔느니라"}}))

    lines = asyncio.run(generate_prologue("해운대구", {"name": "동백섬"}))

    assert lines == fallback_prologue("해운대구", "동백섬")
    assert len(lines) == 24
    assert "해운대구" in lines[0]["text"]
    assert "{name}" in lines[0]["text"]              # 플레이어 이름은 앱이 나중에 치환


def test_비JSON_응답도_지역명_치환_폴백으로_떨어진다(monkeypatch):
    _patch_llm(monkeypatch, "이건 JSON이 아니니라")

    lines = asyncio.run(generate_prologue("종로구", None))

    assert lines == fallback_prologue("종로구", "종로구")   # 첫 장소 없으면 region으로 대체
    assert len(lines) == 24
