# ============================================================
# [v1] 위시 앵커 hook 테스트 — select_wishlist_anchors 단위 검증
# pipeline: AI 백엔드 / 시나리오 (테스트)
# 구현(요약): 정상(매칭)·엣지(반경 밖 합성+WARN)·결정 B(nodes=[])·결정 C(캡 없음)·
#            content_id 중복 제거·좌표 결측을 plain assert로 검증.
#            pytest 없이도 실행: `PYTHONPATH=. python tests/scenario/test_wishlist.py`
#            (pytest 설치 시 `PYTHONPATH=. pytest tests/scenario/test_wishlist.py`도 호환)
# 구현일: 2026-06-30 | 작성: 정찬희 (wishlist-anchor/jch/v1)
# ============================================================
import logging

from app.scenario.request import WishItem
from app.scenario.wishlist import (
    OUT_OF_RADIUS_FLAG,
    SOURCE_WISHLIST,
    WISH_NODE_PREFIX,
    select_wishlist_anchors,
)

_WISHLIST_LOGGER = "app.scenario.wishlist"


def _node(content_id: str, node_id: str, name: str, map_x: float, map_y: float) -> dict:
    """tour_content_id를 가진 반경 내 후보 노드(실데이터 정규화 형태) 픽스처."""
    return {
        "node_id": node_id,
        "tour_content_id": content_id,
        "name": name,
        "map_x": map_x,
        "map_y": map_y,
        "dist_m": 120.0,
        "source": "TourAPI",
    }


class _CaptureHandler(logging.Handler):
    """wishlist 로거의 레코드를 모으는 테스트용 핸들러(WARN 발생 검증)."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _capture_wishlist_logs() -> _CaptureHandler:
    """wishlist 로거에 캡처 핸들러를 부착하고 반환."""
    handler = _CaptureHandler()
    logging.getLogger(_WISHLIST_LOGGER).addHandler(handler)
    return handler


def _has_warning(handler: _CaptureHandler) -> bool:
    """캡처된 레코드 중 WARNING 이상이 있는지."""
    return any(r.levelno == logging.WARNING for r in handler.records)


def test_empty_wishlist_returns_empty() -> None:
    """위시리스트가 비면 [] 반환(no-op, 거리순 동선 보존)."""
    nodes = [_node("100", "tour_100", "경복궁", 126.977, 37.5796)]
    assert select_wishlist_anchors(nodes, []) == []


def test_matched_wish_returns_node_as_anchor() -> None:
    """정상: content_id 매칭 위시 → 해당 노드가 앵커로 반환(source 마킹, 원본 보존)."""
    nodes = [
        _node("100", "tour_100", "경복궁", 126.977, 37.5796),
        _node("200", "tour_200", "창덕궁", 126.991, 37.5794),
    ]
    anchors = select_wishlist_anchors(nodes, [WishItem(content_id="200")])
    assert len(anchors) == 1
    anchor = anchors[0]
    assert anchor["node_id"] == "tour_200"
    assert anchor["name"] == "창덕궁"
    assert anchor["source"] == SOURCE_WISHLIST
    assert anchor[OUT_OF_RADIUS_FLAG] is False
    assert anchor["dist_m"] == 120.0  # 원본 노드 정보 보존


def test_unmatched_wish_synthesizes_node_with_warn() -> None:
    """엣지: 매칭 안 되는 위시(반경 밖) → 좌표 합성 노드 + WARN."""
    nodes = [_node("100", "tour_100", "경복궁", 126.977, 37.5796)]
    handler = _capture_wishlist_logs()
    anchors = select_wishlist_anchors(
        nodes, [WishItem(content_id="999", lat=37.58, lng=126.98)]
    )
    assert len(anchors) == 1
    anchor = anchors[0]
    assert anchor["node_id"] == f"{WISH_NODE_PREFIX}999"
    assert anchor["map_x"] == 126.98   # lng → map_x
    assert anchor["map_y"] == 37.58    # lat → map_y
    assert anchor["dist_m"] is None
    assert anchor["name"] is None
    assert anchor["source"] == SOURCE_WISHLIST
    assert anchor[OUT_OF_RADIUS_FLAG] is True
    assert _has_warning(handler), "반경 밖 위시는 WARN 로그를 남겨야 함"


def test_empty_nodes_with_wishlist_returns_wishlist_only() -> None:
    """결정 B: 반경 내 후보 0개 + 위시 있음 → 위시 합성 앵커만 반환(hook 레벨)."""
    anchors = select_wishlist_anchors(
        [], [WishItem(content_id="999", lat=37.58, lng=126.98)]
    )
    assert len(anchors) == 1
    assert anchors[0]["node_id"] == f"{WISH_NODE_PREFIX}999"
    assert anchors[0][OUT_OF_RADIUS_FLAG] is True


def test_duplicate_content_id_deduped() -> None:
    """엣지: 동일 content_id 중복 위시 → dedupe(앵커 1개)."""
    nodes = [_node("200", "tour_200", "창덕궁", 126.991, 37.5794)]
    anchors = select_wishlist_anchors(
        nodes, [WishItem(content_id="200"), WishItem(content_id="200")]
    )
    assert len(anchors) == 1


def test_no_cap_more_than_count() -> None:
    """결정 C: 위시 앵커 수가 많아도 hook은 전부 반환(캡 금지 — hook 레벨)."""
    nodes = [
        _node(str(i), f"tour_{i}", f"명소{i}", 126.9 + i / 1000, 37.5 + i / 1000)
        for i in range(5)
    ]
    wishes = [WishItem(content_id=str(i)) for i in range(5)]
    anchors = select_wishlist_anchors(nodes, wishes)
    assert len(anchors) == 5


def test_unmatched_wish_missing_coords_still_included() -> None:
    """엣지: 매칭 없음 + 좌표 결측 → 합성 앵커(좌표 None)지만 포함 + WARN."""
    handler = _capture_wishlist_logs()
    anchors = select_wishlist_anchors([], [WishItem(content_id="777")])  # lat/lng None
    assert len(anchors) == 1
    anchor = anchors[0]
    assert anchor["node_id"] == f"{WISH_NODE_PREFIX}777"
    assert anchor["map_x"] is None and anchor["map_y"] is None
    assert _has_warning(handler)


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
