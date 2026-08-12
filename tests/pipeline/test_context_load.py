# ============================================================
# [v1] context_load 테스트 — use_rag 보존 (실행 검증 중 발견한 버그)
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (테스트)
# 구현(요약): 정상(호출측이 준 use_rag=True가 그대로 보존됨 — 전에는 무조건 False로
#            덮어써서 retrieve 노드가 영영 못 탔음)·회귀(미지정 시 기존처럼 False 기본값),
#            2가지를 plain assert로 검증.
#            pytest 없이도 실행: `PYTHONPATH=. python tests/pipeline/test_context_load.py`
# 구현일: 2026-08-12 | 작성: 정찬희
# ============================================================
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.pipeline.nodes.context_load import context_load

_MOD = "app.pipeline.nodes.context_load"


def test_use_rag_true_is_preserved_not_overwritten():
    """정상(회귀 버그 수정): 호출측이 use_rag=True로 넣으면 그대로 유지된다.

    수정 전에는 항상 {"use_rag": False}를 반환해 retrieve 노드가 구조적으로
    도달 불가능했음(app/pipeline/graph.py의 조건 엣지가 이 값을 본다).
    """
    region_cache = MagicMock()
    region_cache.get_text = AsyncMock(return_value="경복궁 개요")

    with patch(f"{_MOD}.get_region_cache", return_value=region_cache):
        result = asyncio.run(context_load({"node_id": "tour_1", "use_rag": True}))

    assert result["use_rag"] is True


def test_use_rag_defaults_to_false_when_unset():
    """회귀: use_rag를 안 넣으면 기존처럼 False 기본값."""
    region_cache = MagicMock()
    region_cache.get_text = AsyncMock(return_value="경복궁 개요")

    with patch(f"{_MOD}.get_region_cache", return_value=region_cache):
        result = asyncio.run(context_load({"node_id": "tour_1"}))

    assert result["use_rag"] is False
    assert result["context"] == "경복궁 개요"


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
