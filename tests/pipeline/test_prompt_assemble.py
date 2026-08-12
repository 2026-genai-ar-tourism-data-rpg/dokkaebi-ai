# ============================================================
# [v1] prompt_assemble 테스트 — npc_dialogue_v1 템플릿(13-B)
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (테스트)
# 구현(요약): 정상(persona·grounding·stage 전부 반영)·엣지(필드 비어도 기본값으로 안 죽음)
#            2가지를 plain assert로 검증.
#            pytest 없이도 실행: `PYTHONPATH=. python tests/pipeline/test_prompt_assemble.py`
# 구현일: 2026-08-12 | 작성: 정찬희
# ============================================================
import asyncio

from app.pipeline.nodes.prompt_assemble import prompt_assemble


def test_assembles_all_fields_into_template():
    """정상: persona·grounding·stage·player_state·query가 전부 프롬프트에 반영됨."""
    state = {
        "node_id": "tour_1",
        "node_name": "광화문",
        "stage": "의뢰",
        "persona": {
            "name": "글빛 도깨비", "archetype": "persona",
            "motif": "세종대왕", "persona": "자애로운 학구적 어조",
        },
        "context": "광화문은 조선 법궁 경복궁의 정문이다.",
        "player_state": {"stone_progress": 2},
        "query": "여기 뭐 하는 곳이야?",
    }
    result = asyncio.run(prompt_assemble(state))
    prompt = result["prompt"]

    assert "광화문" in prompt
    assert "글빛 도깨비" in prompt
    assert "세종대왕" in prompt
    assert "경복궁의 정문" in prompt
    assert "의뢰" in prompt
    assert "여기 뭐 하는 곳이야?" in prompt


def test_missing_fields_use_defaults_without_crashing():
    """엣지: persona/context/player_state 등이 비어 있어도 기본값으로 조립되고 죽지 않음."""
    result = asyncio.run(prompt_assemble({"node_id": "tour_2"}))
    prompt = result["prompt"]

    assert "tour_2" in prompt  # node_name 없으면 node_id로 대체
    assert "이름 없는 도깨비" in prompt
    assert "등장" in prompt  # stage 기본값


def _run_all() -> int:
    """pytest 없이 직접 실행하는 미니 러너. 실패가 있으면 종료코드 1."""
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys

    sys.exit(_run_all())
