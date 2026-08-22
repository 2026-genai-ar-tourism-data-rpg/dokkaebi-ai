# ============================================================
# [v1] persona_inject 테스트 — LLM 페르소나 합성(8-B) + 캐시
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (테스트)
# 구현(요약): 정상 합성+캐시 반영(재호출 시 LLM 미호출)·LLM 실패 fallback·
#            JSON 파싱 실패 fallback, 3가지를 plain assert로 검증.
#            pytest 없이도 실행: `PYTHONPATH=. python tests/pipeline/test_persona_inject.py`
# 구현일: 2026-08-12 | 작성: 정찬희
# ------------------------------------------------------------
# [v2] 캐시 키에 프롬프트 버전이 들어가는 계약 반영(dialogue-rework/kys/v1).
#      버전 문자열을 리터럴로 박지 않는다 — 프롬프트를 고칠 때마다 올릴 값이라
#      박아 두면 개정할 때마다 테스트가 같이 깨진다.
# 구현일: 2026-08-19 | 작성: kys
# ============================================================
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.config import get_settings
from app.core.cache import MemoryCache
from app.core.exceptions import LLMCallError
from app.pipeline.nodes.persona_inject import persona_inject

_MOD = "app.pipeline.nodes.persona_inject"


def _region_cache_mock(overview: str = "경복궁 개요"):
    mock = MagicMock()
    mock.get_text = AsyncMock(return_value=overview)
    return mock


def test_synthesize_success_and_cached_on_second_call():
    """정상: LLM 합성 성공 → persona 반환 + 캐시 저장, 재호출은 LLM을 다시 안 탐."""
    llm_json = (
        '{"name":"글빛 도깨비","archetype":"persona","motif":"세종대왕",'
        '"persona":"자애로운 학구적 어조","appearance_tags":["곤룡포"]}'
    )
    with (
        patch(f"{_MOD}.get_cache", return_value=MemoryCache()),
        patch(f"{_MOD}.get_region_cache", return_value=_region_cache_mock()),
        patch(f"{_MOD}._llm.generate", new=AsyncMock(return_value=llm_json)) as mock_llm,
    ):
        state = {"node_id": "tour_1", "node_name": "경복궁", "stage": "등장"}
        first = asyncio.run(persona_inject(state))
        second = asyncio.run(persona_inject(state))

    assert first["persona"]["archetype"] == "persona"
    assert first["persona"]["motif"] == "세종대왕"
    # 프롬프트를 고치면 이 버전이 올라가고, 그 순간 옛 대사 캐시가 통째로 무효화된다.
    assert first["cache_key"] == f"npc:{get_settings().prompt_version}:tour_1:등장"
    assert second["persona"] == first["persona"]
    mock_llm.assert_called_once()  # 두 번째 호출은 캐시에서 서빙


def test_llm_failure_falls_back_to_guardian():
    """예외: LLM 호출 실패 → guardian 기본값으로 진행(대화 자체는 안 막음)."""
    with (
        patch(f"{_MOD}.get_cache", return_value=MemoryCache()),
        patch(f"{_MOD}.get_region_cache", return_value=_region_cache_mock()),
        patch(f"{_MOD}._llm.generate", new=AsyncMock(side_effect=LLMCallError("일시 오류"))),
    ):
        result = asyncio.run(persona_inject({"node_id": "tour_2", "node_name": "창덕궁", "stage": "등장"}))

    assert result["persona"]["archetype"] == "guardian"


def test_malformed_json_falls_back_to_guardian():
    """예외: LLM이 JSON이 아닌 텍스트를 반환 → guardian 기본값(+ node_name 없으면 node_id로 title 대체)."""
    with (
        patch(f"{_MOD}.get_cache", return_value=MemoryCache()),
        patch(f"{_MOD}.get_region_cache", return_value=_region_cache_mock()),
        patch(f"{_MOD}._llm.generate", new=AsyncMock(return_value="죄송합니다, 모르겠습니다.")),
    ):
        result = asyncio.run(persona_inject({"node_id": "tour_3", "node_name": "", "stage": "등장"}))

    assert result["persona"]["archetype"] == "guardian"
    assert result["persona"]["name"] == "tour_3 도깨비"


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
