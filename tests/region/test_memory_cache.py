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
from app.tourapi.client import TourAPIError


def test_get_text_hit_does_not_refetch():
    """정상: 웜된 지역에 노드가 있으면 TourAPI를 건드리지 않고 바로 반환."""
    cache = RegionMemoryCache(max_regions=2)
    cache.warm("종로", {"tour_1": "경복궁 개요"})

    with patch(
        "app.region.memory_cache._tour.detail_common", new=AsyncMock()
    ) as mock_detail:
        text = asyncio.run(cache.get_text("tour_1"))

    assert text == "경복궁 개요"
    mock_detail.assert_not_called()


def test_get_text_miss_refetches_and_caches():
    """미스: TourAPI 단건 재조회로 채우고, 다음 조회부터는 캐시에서 서빙(재호출 없음)."""
    cache = RegionMemoryCache(max_regions=2)

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
    cache = RegionMemoryCache(max_regions=2)

    with patch(
        "app.region.memory_cache._tour.detail_common",
        new=AsyncMock(side_effect=TourAPIError("일시 오류")),
    ):
        text = asyncio.run(cache.get_text("tour_3"))

    assert text is None


def test_get_text_skips_refetch_for_non_tour_node():
    """엣지: TourAPI 원본이 없는 합성 노드는 재조회를 시도하지 않는다.

    [v3] 위시 노드(wish_<contentId>)는 여기서 제외됐다 — 자동완성에서 확정한 실제
    contentId를 갖고 있어 상세 조회가 된다(그 전엔 위시 장소만 grounding이 없었다).
    지금 이 케이스에 해당하는 건 식음(contentTypeId 39, overview 없음)·mock 노드다.
    """
    cache = RegionMemoryCache(max_regions=2)

    with patch(
        "app.region.memory_cache._tour.detail_common", new=AsyncMock()
    ) as mock_detail:
        assert asyncio.run(cache.get_text("food_mock_0")) is None   # mock 식음
        assert asyncio.run(cache.get_text("synthetic")) is None     # 접두 없음

    mock_detail.assert_not_called()



# ── [v2] 미스 재조회가 지역 슬롯을 잠식하지 않는지 (dialogue-rework/kys/v1) ──
def test_refetch_does_not_evict_real_region():
    """실측 회귀: 재조회가 node_id를 지역 키로 써서 미스 8번이면 진짜 지역이 밀려났다."""
    cache = RegionMemoryCache(max_regions=8)
    cache.warm("종로", {"tour_1604697": "세종로공원 원문"})

    with patch(
        "app.region.memory_cache._tour.detail_common",
        new=AsyncMock(return_value={"overview": "재조회 원문"}),
    ):
        for i in range(10):
            asyncio.run(cache.get_text(f"tour_90000{i}"))

    keys = list(cache._regions.keys())
    assert "종로" in keys, "재조회 반복에 진짜 지역 워킹셋이 evict되면 안 된다"
    assert keys == ["종로", "_orphan"]          # 고아는 버킷 하나만 쓴다
    assert asyncio.run(cache.get_text("tour_1604697")) == "세종로공원 원문"


def test_refetch_uses_given_region():
    """region_id를 알면 그 지역 워킹셋에 편입한다(고아 버킷을 만들지 않는다)."""
    cache = RegionMemoryCache(max_regions=8)

    with patch(
        "app.region.memory_cache._tour.detail_common",
        new=AsyncMock(return_value={"overview": "원문"}),
    ):
        asyncio.run(cache.get_text("tour_1364932", region_id="종로"))

    assert list(cache._regions.keys()) == ["종로"]



def test_refetch_supports_wishlist_and_food_nodes():
    """<출처>_<contentId> 규약이면 재조회한다 — 위시 앵커·식음 노드 포함."""
    cache = RegionMemoryCache(max_regions=8)

    with patch(
        "app.region.memory_cache._tour.detail_common",
        new=AsyncMock(return_value={"overview": "경복궁 원문"}),
    ) as detail:
        text = asyncio.run(cache.get_text("wish_126508", region_id="종로"))
        food = asyncio.run(cache.get_text("food_2543919", region_id="종로"))

    assert text == "경복궁 원문"
    assert food == "경복궁 원문"       # 같은 스텁 — 식음도 조회 대상이라는 뜻
    assert [c.args[0] for c in detail.await_args_list] == ["126508", "2543919"]


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
