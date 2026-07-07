# ============================================================
# [v1] 동선 정렬·backfill 테스트 — build_route ③~⑥ 단계 검증
# pipeline: AI 백엔드 / 시나리오 (테스트)
# 구현(요약): (1) 2-opt가 꼬인 경로를 풀어 총거리를 줄인다,
#            (2) NN 정렬이 출발점 최근접부터 이어간다,
#            (3) 폴백(출발좌표 없음)은 dist_m 순 + None 노드는 맨 뒤,
#            (4) 좌표 결측 위시 앵커는 드롭(500 방지), (5) 위시 앵커 dist_m backfill.
#            pytest 없이도 실행: `PYTHONPATH=. python tests/scenario/test_route_order.py`
# 구현일: 2026-07-06 | 작성: kys (route-nn/kys/v1)
# ============================================================
from app.scenario.request import WishItem
from app.scenario.route_builder import (
    _nearest_neighbor,
    _order_route,
    _path_len,
    _two_opt,
    build_route,
)


def _n(nid: str, lng: float, lat: float, **extra) -> dict:
    """map_x=경도(lng), map_y=위도(lat) 노드 픽스처."""
    return {"node_id": nid, "map_x": lng, "map_y": lat, **extra}


# 정사각형 꼭짓점 — 대각으로 꼬아둔 초기 순서(교차)
_A = _n("A", 126.980, 37.570)
_B = _n("B", 126.980, 37.572)
_C = _n("C", 126.982, 37.570)
_D = _n("D", 126.982, 37.572)
_SX, _SY = 126.979, 37.571


def test_two_opt_uncrosses_and_shortens():
    crossed = [_A, _D, _C, _B]
    fixed = _two_opt(crossed, _SX, _SY)
    assert _path_len(fixed, _SX, _SY) < _path_len(crossed, _SX, _SY)


def test_two_opt_keeps_optimal_as_is():
    # 이미 최적이면 2-opt가 더 나쁘게 만들지 않는다(단조 개선).
    good = _nearest_neighbor([_A, _B, _C, _D], _SX, _SY)
    opt = _two_opt(good, _SX, _SY)
    assert _path_len(opt, _SX, _SY) <= _path_len(good, _SX, _SY) + 1e-6


def test_nearest_neighbor_starts_from_closest():
    # 출발점(126.979,37.570)에 가장 가까운 노드가 첫 방문.
    nodes = [_n("far", 126.990, 37.570), _n("near", 126.9795, 37.570)]
    order = _nearest_neighbor(nodes, 126.979, 37.570)
    assert order[0]["node_id"] == "near"


def test_fallback_sorts_by_dist_none_last():
    # 출발좌표 없음 → dist_m 순, dist_m=None은 맨 뒤(예전엔 0.0 취급돼 맨 앞 튐).
    route = [
        _n("mid", 0, 0, dist_m=200),
        _n("none", 0, 0, dist_m=None),
        _n("near", 0, 0, dist_m=50),
    ]
    order = _order_route(route, None, None)
    assert [n["node_id"] for n in order] == ["near", "mid", "none"]


def test_build_route_drops_coordless_wish_no_crash():
    # 좌표 없는 위시(앱이 좌표 안 보낸 케이스) → 드롭, 500 안 남.
    nodes = [_n(f"s{i}", 126.980 + i * 0.001, 37.570, dist_m=i * 100.0) for i in range(4)]
    route = build_route(
        nodes, count=3, start_x=126.979, start_y=37.570,
        wishlist=[WishItem(content_id="999", name="좌표없음")],  # lat/lng 결측
    )
    assert all(n.get("map_x") is not None and n.get("map_y") is not None for n in route)
    assert not any(str(n["node_id"]).startswith("wish_") for n in route)


def test_build_route_backfills_wish_dist_m():
    # 좌표 있는 반경밖 위시 → 합성 앵커 포함 + dist_m 출발점 기준 backfill.
    nodes = [_n(f"s{i}", 126.980 + i * 0.001, 37.570, dist_m=i * 100.0) for i in range(4)]
    route = build_route(
        nodes, count=5, start_x=126.979, start_y=37.570,
        wishlist=[WishItem(content_id="777", name="먼곳", lat=37.590, lng=126.999)],
    )
    wish = [n for n in route if str(n["node_id"]).startswith("wish_")]
    assert len(wish) == 1
    assert wish[0]["name"] == "먼곳"
    assert wish[0]["dist_m"] is not None and wish[0]["dist_m"] > 0
    # 모든 노드 dist_m 채워짐(표시 일관성)
    assert all(n.get("dist_m") is not None for n in route)


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all passed")
