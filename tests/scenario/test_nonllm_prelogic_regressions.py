import asyncio

import pytest

import app.scenario.generator as generator
from app.core.exceptions import DokkaebiAIError
from app.scenario.request import LatLng, ScenarioRequest, WishItem
from app.scenario.route_builder import _path_len, _select_count
from app.tourapi.food import interleave_food_async


def _node(node_id: str, x: float, y: float, **extra) -> dict:
    return {
        "node_id": node_id,
        "name": node_id,
        "map_x": x,
        "map_y": y,
        "dist_m": extra.pop("dist_m", 1.0),
        **extra,
    }


def test_generate_scenario_uses_start_as_end_when_omitted(monkeypatch):
    captured = {}

    async def fake_generate_basic(*args, **kwargs):
        captured.update(kwargs)
        return {}

    monkeypatch.setattr(generator, "generate_basic_scenario", fake_generate_basic)
    req = ScenarioRequest(user_id="u", start=LatLng(lat=37.57, lng=126.98))
    asyncio.run(generator.generate_scenario(req))

    assert captured["end_x"] == req.start.lng
    assert captured["end_y"] == req.start.lat


def test_path_len_counts_final_leg_to_end():
    route = [_node("a", 126.981, 37.570)]
    open_len = _path_len(route, 126.980, 37.570)
    roundtrip_len = _path_len(route, 126.980, 37.570, 126.980, 37.570)
    assert roundtrip_len > open_len


def test_select_count_dedupes_anchor_and_preserves_metadata():
    anchors = [
        _node("same", 126.98, 37.57, source="wishlist"),
        _node("same", 126.98, 37.57, density_tier="low_traffic"),
    ]
    selected = _select_count([], anchors, count=3)
    assert len(selected) == 1
    assert selected[0]["source"] == "wishlist"
    assert selected[0]["density_tier"] == "low_traffic"


def test_coordless_wishlist_only_raises_domain_error(monkeypatch):
    async def no_nodes(*args, **kwargs):
        return []

    monkeypatch.setattr(generator._tour, "location_based_list", no_nodes)
    with pytest.raises(DokkaebiAIError, match="배치 가능한 관광지"):
        asyncio.run(generator.generate_basic_scenario(
            126.98,
            37.57,
            radius_m=100,
            count=3,
            with_dialogue=False,
            with_content=False,
            no_meals=True,
            wishlist=[WishItem(content_id="x")],
        ))


def test_async_food_path_awaits_candidate_fetch(monkeypatch):
    route = [
        _node("a", 126.980, 37.570),
        _node("b", 126.990, 37.570),
    ]
    calls = []

    async def fake_nearby(map_x, map_y, **kwargs):
        calls.append((map_x, map_y))
        return [{
            "node_id": "food_1",
            "name": "식당",
            "kind": "food",
            "price_band": 2,
            "price_band_label": "₩₩",
            "map_x": map_x,
            "map_y": map_y,
        }]

    monkeypatch.setattr("app.tourapi.food.nearby_food_async", fake_nearby)
    out = asyncio.run(interleave_food_async(route, budget=20_000, per_route=1))
    assert calls
    assert any(node.get("kind") == "food" for node in out)
