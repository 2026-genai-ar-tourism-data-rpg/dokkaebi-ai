# ============================================================
# [v1] 테스트: 코스 오프닝 프롤로그 생성
# pipeline: AI 백엔드 / 시나리오 (생성 회귀 방지, 네트워크·실 LLM 0)
# 커버: ① 정상 생성 — LLM이 20개 텍스트 슬롯을 채우면 24줄(beat 포함)로 정확히 병합된다
#       ② 생성 실패(비JSON·슬롯 수 불일치) — 지역명만 반영한 고정 대본으로 폴백,
#          {name} 플레이스홀더는 그대로 남는다
# 구현일: 2026-09-04 | 작성: Claude (prologue-story-gen/claude/v1)
# ============================================================
import asyncio
import json

from app.scenario import prologue_content
from app.scenario.prologue_content import _SKELETON, _TEXT_SLOTS, fallback_prologue, generate_prologue


def _patch_llm(monkeypatch, reply: str):
    async def fake_generate(prompt, **kwargs):
        return reply

    monkeypatch.setattr(prologue_content._llm, "generate", fake_generate)


def test_정상_생성이면_20개_슬롯을_스켈레톤_순서대로_채운다(monkeypatch):
    texts = [f"대사{i}" for i in range(len(_TEXT_SLOTS))]
    _patch_llm(monkeypatch, json.dumps({"lines": texts}))

    lines = asyncio.run(generate_prologue("강남구", {"name": "봉은사"}))

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


def test_슬롯_수가_안_맞으면_지역명_치환_폴백으로_24줄을_보장한다(monkeypatch):
    _patch_llm(monkeypatch, json.dumps({"lines": ["딱 하나만 왔느니라"]}))

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
