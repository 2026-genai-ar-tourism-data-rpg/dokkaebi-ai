# ============================================================
# [v1] 위시 전용 코스(wishlist_only) — 앱 퀘스트 탭 위시리스트 '코스 생성'은 고른 장소로만.
# pipeline: AI 백엔드 / 시나리오 (노드 선택)
# 구현(요약): build_route가 위시 앵커만으로 경로를 짜는지(거리순 채움·비인기 앵커 없음),
#            플래그가 없으면 예전처럼 count까지 채우는지, API가 플래그를 생성기로 넘기는지.
# 구현일: 2026-09-19 | 작성: ljs (wishlist-only/ljs/v1)
# ============================================================
from fastapi.testclient import TestClient

import app.scenario.route_builder as route_builder
from app.main import create_app
from app.scenario.request import WishItem
from app.scenario.route_builder import build_route


def _node(content_id: str, name: str, map_x: float, dist_m: float) -> dict:
    return {
        "node_id": f"tour_{content_id}",
        "tour_content_id": content_id,
        "name": name,
        "map_x": map_x,
        "map_y": 37.57,
        "dist_m": dist_m,
        "source": "TourAPI",
    }


_NODES = [_node(str(100 + i), f"후보{i}", 126.98 + i * 0.002, i * 150.0) for i in range(6)]
_WISH = [WishItem(content_id="102"), WishItem(content_id="104")]


def test_위시_전용이면_고른_장소로만_경로를_짠다():
    route = build_route(_NODES, count=5, start_x=126.98, start_y=37.57, wishlist=_WISH,
                        no_meals=True, wishlist_only=True)
    assert sorted(n["tour_content_id"] for n in route) == ["102", "104"]


def test_반경_밖_위시도_합성_노드로_들어가고_채우지_않는다():
    far = [WishItem(content_id="999", name="먼 곳", lat=37.60, lng=127.05)]
    route = build_route(_NODES, count=5, start_x=126.98, start_y=37.57, wishlist=far,
                        no_meals=True, wishlist_only=True)
    assert [n.get("tour_content_id") or n.get("content_id") for n in route] == ["999"]


def test_플래그가_없으면_예전처럼_count까지_채운다():
    route = build_route(_NODES, count=5, start_x=126.98, start_y=37.57, wishlist=_WISH, no_meals=True)
    assert len(route) == 5
    assert {"102", "104"} <= {n["tour_content_id"] for n in route}


def test_위시_전용이면_비인기_앵커를_부르지_않는다(monkeypatch):
    def _boom(*_a, **_k):
        raise AssertionError("위시 전용에서 비인기 앵커를 넣으면 안 된다")

    monkeypatch.setattr(route_builder, "select_lowtraffic_anchors", _boom)
    route = build_route(_NODES, count=5, start_x=126.98, start_y=37.57, wishlist=_WISH,
                        no_meals=True, lowtraffic_k=2, wishlist_only=True)
    assert len(route) == 2


def test_API가_wishlist_only를_생성기로_넘긴다(monkeypatch):
    import app.api.routes as routes

    seen = {}

    async def _fake(req):
        seen["wishlist_only"] = req.wishlist_only
        return {"scenario_id": "s1", "title": "t", "region": "r", "node_sequence": []}

    monkeypatch.setattr(routes, "generate_scenario", _fake)
    client = TestClient(create_app())
    body = {"user_id": "u", "start": {"lat": 37.57, "lng": 126.98}, "wishlist": [{"content_id": "102"}]}

    client.post("/v1/scenarios", json={**body, "wishlist_only": True})
    assert seen["wishlist_only"] is True
    client.post("/v1/scenarios", json=body)
    assert seen["wishlist_only"] is False, "기본은 예전처럼 채운다"
