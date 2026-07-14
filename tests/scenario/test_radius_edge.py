# ============================================================
# [v1] 결정 B/C 테스트 — 반경 0개 폴백(B) + 앵커 캡 제거(C)
# pipeline: AI 백엔드 / 시나리오 (테스트)
# 구현(요약): B=generator.generate_basic_scenario 빈노드 가드(위시 있으면 raise 안 함,
#            없으면 기존처럼 raise) / C=route_builder._select_count가 앵커를 count로
#            잘라내지 않음(앵커<=count 회귀도 함께 확인).
#            pytest 없이도 실행: `PYTHONPATH=. python tests/scenario/test_radius_edge.py`
# 구현일: 2026-07-14 | 작성: 정찬희 (radius-edge/jch/v1)
# ============================================================
import asyncio

from app.core.exceptions import DokkaebiAIError
from app.scenario.generator import generate_basic_scenario
from app.scenario.request import WishItem
from app.scenario.route_builder import _select_count

# 종로 mock 노드(client.py)에서 아주 멀리 떨어진 좌표(제주) — 어떤 반경으로도 매칭 안 됨.
_FAR_X, _FAR_Y = 126.5311, 33.4996


def _n(nid: str, dist_m: float = 100.0) -> dict:
    """_select_count는 node_id만 보고 선택하므로 좌표는 아무 값이나 채운 최소 픽스처."""
    return {"node_id": nid, "map_x": 126.98, "map_y": 37.57, "dist_m": dist_m}


def test_select_count_preserves_anchors_beyond_count():
    """결정 C: 앵커 수(4) > count(2) → 앵커 전부 보존(잘리지 않음)."""
    anchors = [_n(f"a{i}") for i in range(4)]
    nodes = [_n(f"n{i}") for i in range(3)]
    selected = _select_count(nodes, anchors, count=2)
    assert len(selected) == 4
    assert {n["node_id"] for n in selected} == {"a0", "a1", "a2", "a3"}


def test_select_count_fills_to_count_when_anchors_leq_count():
    """회귀: 앵커(1) <= count(3) → 앵커 + 가까운 후보로 count개까지 채움(기존 동작 유지)."""
    anchors = [_n("a0")]
    nodes = [_n(f"n{i}") for i in range(5)]
    selected = _select_count(nodes, anchors, count=3)
    assert len(selected) == 3
    assert selected[0]["node_id"] == "a0"


def test_empty_radius_with_wishlist_builds_wish_only_route():
    """결정 B: 반경 내 후보 0개 + 위시 있음 → raise 안 하고 위시 앵커만으로 경로 구성."""
    scn = asyncio.run(generate_basic_scenario(
        _FAR_X, _FAR_Y, radius_m=100, count=3,
        with_dialogue=False, with_content=False, no_meals=True,
        wishlist=[WishItem(content_id="1", name="위시전용", lat=_FAR_Y, lng=_FAR_X)],
    ))
    assert scn["stone_total"] == 1
    assert scn["node_sequence"][0]["name"] == "위시전용"


def test_empty_radius_without_wishlist_still_raises():
    """회귀: 위시 없이 반경 내 후보 0개면 기존과 동일하게 raise."""
    raised = False
    try:
        asyncio.run(generate_basic_scenario(
            _FAR_X, _FAR_Y, radius_m=100, count=3,
            with_dialogue=False, with_content=False, no_meals=True,
        ))
    except DokkaebiAIError:
        raised = True
    assert raised


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all passed")
