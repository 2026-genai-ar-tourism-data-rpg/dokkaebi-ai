# ============================================================
# [v1] 지역 인메모리 캐시 테스트 — get_text 미스 처리(TourAPI 단건 재조회)
# pipeline: AI 백엔드 / 런타임 데이터 핫 계층 (테스트)
# 구현(요약): 히트(재조회 없음)·미스+재조회 성공(+캐시 반영 확인)·미스+재조회 실패·
#            비-tour_ 접두 노드 스킵, 4가지를 plain assert로 검증.
#            pytest 없이도 실행: `PYTHONPATH=. python tests/region/test_memory_cache.py`
# 구현일: 2026-08-11 | 작성: 정찬희
# ============================================================
import asyncio
from unittest.mock import AsyncMock, patch

from app.region.memory_cache import RegionMemoryCache
from app.scenario.wishlist import WISH_NODE_PREFIX
from app.tourapi.client import TourAPIError


def test_get_text_hit_does_not_refetch():
    """정상: 웜된 지역에 노드가 있으면 TourAPI를 건드리지 않고 바로 반환."""
    cache = RegionMemoryCache(max_regions=2, max_nodes_per_region=10)
    cache.warm("종로", {"tour_1": "경복궁 개요"})

    with patch(
        "app.region.memory_cache._tour.detail_common", new=AsyncMock()
    ) as mock_detail:
        text = asyncio.run(cache.get_text("tour_1"))

    assert text == "경복궁 개요"
    mock_detail.assert_not_called()


def test_get_text_miss_refetches_and_caches():
    """미스: TourAPI 단건 재조회로 채우고, 다음 조회부터는 캐시에서 서빙(재호출 없음)."""
    cache = RegionMemoryCache(max_regions=2, max_nodes_per_region=10)

    with patch(
        "app.region.memory_cache._tour.detail_common",
        new=AsyncMock(return_value={"overview": "창덕궁 개요"}),
    ) as mock_detail:
        first = asyncio.run(cache.get_text("tour_2"))
        second = asyncio.run(cache.get_text("tour_2"))

    assert first == "창덕궁 개요"
    assert second == "창덕궁 개요"
    mock_detail.assert_called_once_with("2")  # "tour_" 접두 제거한 content_id


def test_get_text_miss_refetch_failure_returns_none():
    """예외: TourAPI 재조회가 실패해도 그 노드만 None — 예외를 밖으로 전파하지 않음."""
    cache = RegionMemoryCache(max_regions=2, max_nodes_per_region=10)

    with patch(
        "app.region.memory_cache._tour.detail_common",
        new=AsyncMock(side_effect=TourAPIError("일시 오류")),
    ):
        text = asyncio.run(cache.get_text("tour_3"))

    assert text is None


def test_get_text_skips_refetch_for_non_tour_node():
    """엣지: 위시 합성 노드(tour_ 접두 아님)는 TourAPI 원본이 없으므로 재조회 시도 안 함."""
    cache = RegionMemoryCache(max_regions=2, max_nodes_per_region=10)
    node_id = f"{WISH_NODE_PREFIX}777"

    with patch(
        "app.region.memory_cache._tour.detail_common", new=AsyncMock()
    ) as mock_detail:
        text = asyncio.run(cache.get_text(node_id))

    assert text is None
    mock_detail.assert_not_called()


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
