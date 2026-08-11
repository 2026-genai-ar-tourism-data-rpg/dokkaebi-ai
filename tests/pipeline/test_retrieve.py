# ============================================================
# [v1] retrieve 테스트 — 재랭킹·쿼리변환·저신뢰 재검색
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (테스트)
# 구현(요약): 키워드overlap 재랭킹이 순서를 바꾸는지·저신뢰 시 재작성+재검색으로 개선되는지·
#            재작성 LLM 실패해도 원래 결과로 안전하게 진행하는지·query 없으면 즉시 빈 결과,
#            4가지를 plain assert로 검증.
#            pytest 없이도 실행: `PYTHONPATH=. python tests/pipeline/test_retrieve.py`
# 구현일: 2026-08-12 | 작성: 정찬희
# ============================================================
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.exceptions import LLMCallError
from app.pipeline.nodes.retrieve import retrieve

_MOD = "app.pipeline.nodes.retrieve"


def _region_cache_mock(texts: dict):
    mock = MagicMock()
    mock.get_text = AsyncMock(side_effect=lambda node_id: texts.get(node_id))
    return mock


def test_lexical_overlap_reranks_above_raw_cosine_order():
    """정상: 코사인은 'b'가 위지만 쿼리 키워드가 'a' 텍스트에 다 있으면 재랭킹 후 'a'가 위로 온다."""
    index = MagicMock()
    index.search = MagicMock(return_value=[("b", 0.55), ("a", 0.52)])
    texts = {"a": "경복궁 근정전 답사 코스 안내", "b": "관련 없는 다른 장소 설명"}

    with (
        patch(f"{_MOD}.get_region_index", return_value=index),
        patch(f"{_MOD}.get_region_cache", return_value=_region_cache_mock(texts)),
        patch(f"{_MOD}._embed.embed_one", new=AsyncMock(return_value=[0.1, 0.2])),
    ):
        result = asyncio.run(retrieve({"query": "경복궁 근정전 코스", "region_id": "종로"}))

    assert result["retrieved"][0] == texts["a"]


def test_low_confidence_triggers_rewrite_and_uses_better_retry():
    """예외: 첫 검색 confidence가 임계 미만이면 쿼리 재작성 후 재검색, 개선되면 그 결과를 채택."""
    index = MagicMock()
    index.search = MagicMock(side_effect=[
        [("a", 0.1)],   # 1차: 저신뢰
        [("a", 0.9)],   # 재작성 쿼리로 재검색: 고신뢰
    ])
    texts = {"a": "재작성 후 매칭된 텍스트"}

    with (
        patch(f"{_MOD}.get_region_index", return_value=index),
        patch(f"{_MOD}.get_region_cache", return_value=_region_cache_mock(texts)),
        patch(f"{_MOD}._embed.embed_one", new=AsyncMock(return_value=[0.1, 0.2])),
        patch(f"{_MOD}._llm.generate", new=AsyncMock(return_value="재작성된 검색어")),
    ):
        result = asyncio.run(retrieve({"query": "모호한 질문", "region_id": "종로"}))

    # 정확한 블렌드 점수(코사인*가중 + 키워드overlap*가중)를 하드코딩하지 않고,
    # "재검색으로 임계를 넘어설 만큼 개선됐다 + 실제로 재검색이 일어났다"만 검증.
    assert result["confidence"] > 0.5
    assert result["retrieved"] == [texts["a"]]
    assert index.search.call_count == 2


def test_rewrite_llm_failure_keeps_original_low_confidence_result():
    """예외: 쿼리 재작성 LLM 호출이 실패해도 죽지 않고 1차 검색 결과를 그대로 반환."""
    index = MagicMock()
    index.search = MagicMock(return_value=[("a", 0.1)])
    texts = {"a": "1차 검색 결과 텍스트"}

    with (
        patch(f"{_MOD}.get_region_index", return_value=index),
        patch(f"{_MOD}.get_region_cache", return_value=_region_cache_mock(texts)),
        patch(f"{_MOD}._embed.embed_one", new=AsyncMock(return_value=[0.1, 0.2])),
        patch(f"{_MOD}._llm.generate", new=AsyncMock(side_effect=LLMCallError("일시 오류"))),
    ):
        result = asyncio.run(retrieve({"query": "모호한 질문", "region_id": "종로"}))

    assert result["retrieved"] == [texts["a"]]
    assert index.search.call_count == 1  # 재검색 시도 자체가 없었음


def test_empty_query_returns_immediately_without_search():
    """회귀: query·context 둘 다 없으면 인덱스를 건드리지 않고 빈 결과."""
    index = MagicMock()
    with patch(f"{_MOD}.get_region_index", return_value=index):
        result = asyncio.run(retrieve({"region_id": "종로"}))

    assert result == {"retrieved": [], "confidence": 0.0}
    index.search.assert_not_called()


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
