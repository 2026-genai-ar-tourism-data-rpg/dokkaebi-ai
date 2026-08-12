import asyncio
import threading

import pytest

import app.scenario.generator as generator
from app.core.cache import MemoryCache
from app.core.exceptions import DokkaebiAIError
from app.region.memory_cache import RegionMemoryCache
from app.region.semantic_index import RegionSemanticIndex
from app.scenario.request import LatLng, ScenarioRequest, WishItem
from app.scenario.route_builder import _path_len, _select_count, build_route
from app.tourapi.base import TourAPIError, TourAPITimeoutError
from app.tourapi.food import _normalize_food_item, interleave_food_async
from app.tourapi.google_places import fetch_price_band


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


# --- [v3] 좌표 결측 후보 가드 (ai-logic-fix/pjh/v2) ---

def test_build_route_drops_coordless_candidate_instead_of_crashing():
    """TourAPI가 mapx/mapy를 비워 보낸 후보 1개 때문에 요청 전체가 500이 되면 안 된다."""
    nodes = [
        _node("a", 126.990, 37.570, dist_m=100.0),
        {"node_id": "coordless", "name": "좌표없음", "map_x": None, "map_y": None, "dist_m": 200.0},
        _node("c", 126.980, 37.575, dist_m=300.0),
    ]
    route = build_route(nodes, count=3, start_x=126.99, start_y=37.57, no_meals=True)

    assert [n["node_id"] for n in route] == ["a", "c"]


def test_build_route_drops_coordless_candidate_on_legacy_finale_path():
    """start 좌표 없는 레거시 경로(_place_finale)도 같은 좌표 가드를 받아야 한다."""
    nodes = [
        _node("a", 126.990, 37.570, dist_m=100.0),
        {"node_id": "coordless", "name": "좌표없음", "map_x": None, "map_y": None, "dist_m": 200.0},
        _node("c", 126.980, 37.575, dist_m=300.0),
    ]
    route = build_route(nodes, count=3, end_x=126.980, end_y=37.575, no_meals=True)

    assert [n["node_id"] for n in route] == ["a", "c"]


# --- [v2] 지역 캐시 warm 병합 (ai-logic-fix/pjh/v2) ---

def test_region_cache_warm_merges_instead_of_replacing():
    """두 번째 warm이 앞서 올린 워킹셋을 지우면 grounding이 사라진다(분기 워밍·동시 요청)."""
    cache = RegionMemoryCache(max_regions=2, max_nodes_per_region=10)
    cache.warm("종로", {"tour_1": "경복궁 설명", "tour_2": "창덕궁 설명"})
    cache.warm("종로", {"tour_9": "샛길 설명"})

    assert cache.get_text("tour_1") == "경복궁 설명"
    assert cache.get_text("tour_9") == "샛길 설명"


def test_region_cache_warm_keeps_existing_text_on_empty_overview():
    """overview 조회 실패(빈 문자열)가 이미 확보한 원문을 덮지 않아야 한다."""
    cache = RegionMemoryCache(max_regions=2, max_nodes_per_region=10)
    cache.warm("종로", {"tour_1": "경복궁 설명"})
    cache.warm("종로", {"tour_1": ""})

    assert cache.get_text("tour_1") == "경복궁 설명"


def test_region_cache_bounds_nodes_per_region():
    """병합으로 바뀐 만큼 지역당 노드 수는 LRU 상한으로 묶여야 한다(무한 증식 방지)."""
    cache = RegionMemoryCache(max_regions=2, max_nodes_per_region=2)
    cache.warm("종로", {"n1": "1", "n2": "2"})
    cache.get_text("n1")                      # n1을 최근 사용으로 갱신 → evict 대상은 n2
    cache.warm("종로", {"n3": "3"})

    assert cache.get_text("n1") == "1"
    assert cache.get_text("n3") == "3"
    assert cache.get_text("n2") is None


# --- [v4] 식음 노드 dist_m · headcount 배선 (ai-logic-fix/pjh/v2) ---

def test_food_node_gets_dist_m_after_insertion(monkeypatch):
    """식음 삽입은 build_route의 backfill 이후라, generator가 거리를 다시 채워야 한다."""
    nodes = [
        _node("tour_1", 126.980, 37.570, dist_m=None),
        _node("tour_2", 126.990, 37.570, dist_m=None),
    ]

    async def fake_list(*args, **kwargs):
        return nodes

    async def fake_nearby(map_x, map_y, **kwargs):
        return [{
            "node_id": "food_1", "name": "식당", "kind": "food", "price_band": 1,
            "map_x": map_x, "map_y": map_y,
        }]

    monkeypatch.setattr(generator._tour, "location_based_list", fake_list)
    monkeypatch.setattr("app.tourapi.food.nearby_food_async", fake_nearby)
    monkeypatch.setattr("app.tourapi.food.get_settings", lambda: _settings_with(scenario_food_per_route=1))

    scn = asyncio.run(generator.generate_basic_scenario(
        126.975, 37.570, count=2, with_dialogue=False, with_content=False, budget=20_000,
    ))
    food = [q for q in scn["node_sequence"] if q["kind"] in ("food", "cafe")]
    assert food, "식음 노드가 삽입되지 않았다"
    assert all(q["dist_m"] is not None for q in food)


def test_headcount_reaches_food_gating(monkeypatch):
    """요청의 인원수가 식음 예산 게이팅까지 전달돼야 한다(1인 예산 = budget/headcount)."""
    captured = {}

    async def fake_interleave(route, *, budget=None, headcount=1, **kwargs):
        captured["headcount"] = headcount
        return route

    async def fake_list(*args, **kwargs):
        return [_node("tour_1", 126.980, 37.570), _node("tour_2", 126.990, 37.570)]

    monkeypatch.setattr(generator._tour, "location_based_list", fake_list)
    monkeypatch.setattr(generator, "interleave_food_async", fake_interleave)

    req = ScenarioRequest(
        user_id="u", start=LatLng(lat=37.570, lng=126.975),
        budget=40_000, headcount=4, with_dialogue=False, with_content=False,
    )
    scn = asyncio.run(generator.generate_scenario(req))

    assert captured["headcount"] == 4
    assert scn["headcount"] == 4


def _settings_with(**overrides):
    """food 모듈이 보는 설정만 일부 덮어쓴 가짜 settings."""
    from app.config import get_settings

    base = get_settings()

    class _S:
        def __getattr__(self, name):
            if name in overrides:
                return overrides[name]
            return getattr(base, name)

    return _S()


# --- [v4] 좌표 결측 식음 후보 / priceLevel 가드 (ai-logic-fix/pjh/v2) ---

def test_normalize_food_item_drops_coordless():
    """좌표 없는 식음 후보 1개가 후보 리스트 전체를 mock으로 떨어뜨리면 안 된다."""
    assert _normalize_food_item({"contentid": "1", "title": "가", "mapx": "", "mapy": ""}) is None
    assert _normalize_food_item({"contentid": "2", "title": "나", "mapx": "126.98"}) is None
    ok = _normalize_food_item({"contentid": "3", "title": "다", "mapx": "126.98", "mapy": "37.57"})
    assert ok is not None and ok["map_x"] == 126.98


def test_fetch_price_band_returns_none_for_coordless(monkeypatch):
    """좌표가 없으면 캐시 키 계산(round)에서 터지지 않고 '미상'으로 떨어져야 한다."""
    monkeypatch.setattr(
        "app.tourapi.google_places.get_settings", lambda: _settings_with(google_maps_api_key="dummy")
    )
    assert asyncio.run(fetch_price_band("가게", None, None)) is None


# --- [v2] TourAPI 장애 예외 분류 (ai-logic-fix/pjh/v2) ---

def test_tourapi_timeout_is_distinguishable_from_result_error():
    """타임아웃(재시도 가능)과 결과 오류를 앱이 구분할 수 있어야 한다(503 vs 502)."""
    assert issubclass(TourAPITimeoutError, TourAPIError)
    assert not isinstance(TourAPIError("결과오류"), TourAPITimeoutError)


# --- [v2] MemoryCache 상한 (ai-logic-fix/pjh/v2) ---

def test_memory_cache_bounds_entries():
    """만료됐지만 재조회되지 않는 키가 무한정 쌓이면 안 된다."""
    cache = MemoryCache(max_entries=3)
    for i in range(10):
        asyncio.run(cache.set(f"k{i}", "v", 3600))

    assert len(cache._store) <= 3
    assert asyncio.run(cache.get("k9")) == "v"      # 최신 항목은 남는다


# --- [v2] 의미검색 인덱스 입력 검증 (ai-logic-fix/pjh/v2) ---

def test_semantic_index_rejects_length_mismatch():
    """node_ids/vectors 길이가 어긋나면 조용히 틀린 검색결과를 내지 말고 즉시 실패."""
    index = RegionSemanticIndex("종로", dim=3)
    with pytest.raises(ValueError, match="개수 불일치"):
        index.add(["a", "b"], [[1.0, 0.0, 0.0]])


# --- [v3] 이벤트 루프 블로킹 (ai-logic-fix/pjh/v2) ---

def test_build_route_runs_off_the_event_loop(monkeypatch):
    """비인기 앵커 hook이 동기 httpx를 부르므로 build_route는 워커 스레드에서 돌아야 한다.

    메인 스레드에서 돌면 그 동안 이벤트 루프가 멈춰 서버의 모든 요청이 대기한다.
    """
    seen = {}

    async def fake_list(*args, **kwargs):
        return [_node("tour_1", 126.980, 37.570), _node("tour_2", 126.990, 37.570)]

    def fake_build_route(nodes, **kwargs):
        seen["thread"] = threading.current_thread()
        return list(nodes)

    monkeypatch.setattr(generator._tour, "location_based_list", fake_list)
    monkeypatch.setattr(generator, "build_route", fake_build_route)

    asyncio.run(generator.generate_basic_scenario(
        126.975, 37.570, count=2, with_dialogue=False, with_content=False, no_meals=True,
    ))

    assert seen["thread"] is not threading.main_thread()


def test_density_snapshot_fetched_once_under_concurrency(monkeypatch):
    """to_thread로 동시 요청이 가능해진 만큼, 같은 지역 snapshot은 한 번만 fetch해야 한다."""
    import app.tourapi.bigdata as bigdata

    calls = []
    bigdata._DENSITY_SNAPSHOT_CACHE.clear()

    def fake_fetch(s, region, area_cd, signgu_cd, base_ym, cache_key):
        calls.append(cache_key)
        snapshot = {"region": region, "areaCd": area_cd, "signguCd": signgu_cd,
                    "baseYm": base_ym, "concentration_rows": [], "hub_rows": []}
        bigdata._cache_set(bigdata._DENSITY_SNAPSHOT_CACHE, cache_key, snapshot, 60)
        return snapshot

    monkeypatch.setattr(bigdata, "_fetch_density_snapshot", fake_fetch)

    threads = [threading.Thread(target=bigdata.fetch_density_snapshot_sync) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(calls) == 1, f"snapshot이 {len(calls)}번 조회됐다(중복 fetch)"
    bigdata._DENSITY_SNAPSHOT_CACHE.clear()
