# ============================================================
# [v1] 위시 플래그 통과 회귀 테스트 — source/out_of_radius가 generator까지 살아남는지
# pipeline: AI 백엔드 / 시나리오 (테스트)
# 구현(요약): (A) wishlist.py가 마킹한 source·out_of_radius가 generator._build_quest의
#            최종 퀘스트 dict까지 드롭 없이 전달되는지. (B) no_meals=True여도 위시
#            식당(kind=restaurant)이 select_wishlist_anchors를 통해 build_route에 포함되는지
#            (select_wishlist_anchors는 no_meals 파라미터를 받지 않는 의도된 설계 — 위시 우선).
#            pytest 없이도 실행: `PYTHONPATH=. python tests/scenario/test_wishlist_flags.py`
# 구현일: 2026-07-30 | 작성: 정찬희 (wishlist-flags/jch/v1)
# ============================================================
from app.scenario.generator import _build_quest, _plan_nodes
from app.scenario.request import WishItem
from app.scenario.route_builder import build_route
from app.scenario.wishlist import OUT_OF_RADIUS_FLAG, SOURCE_WISHLIST, WISH_NODE_PREFIX


def _out_of_radius_wish_node() -> dict:
    """wishlist._synthesize_anchor 산출 형태(반경 밖 합성 앵커) 픽스처."""
    return {
        "node_id": f"{WISH_NODE_PREFIX}999",
        "name": None,
        "map_x": 126.98,
        "map_y": 37.58,
        "dist_m": None,
        "source": SOURCE_WISHLIST,
        OUT_OF_RADIUS_FLAG: True,
    }


def test_build_quest_propagates_source_and_out_of_radius():
    """테스트 A: 반경 밖 위시 노드의 source·out_of_radius가 _build_quest 결과까지 생존."""
    node = _out_of_radius_wish_node()
    metas = _plan_nodes([node])
    quest = _build_quest(node, 0, metas[0], "종로", "환영하느니라")
    assert quest["source"] == SOURCE_WISHLIST
    assert quest[OUT_OF_RADIUS_FLAG] is True


def test_no_meals_still_includes_wishlist_restaurant_anchor():
    """테스트 B: no_meals=True여도 위시 식당(kind=restaurant)은 build_route에 포함된다.

    select_wishlist_anchors는 no_meals를 받지 않는다(의도된 설계) — no_meals는
    interleave_food(자동 식음 삽입)만 막고, 위시 앵커 강제포함(①)에는 관여하지 않는다.
    """
    wishlist = [WishItem(content_id="1", kind="restaurant", lat=37.58, lng=126.98)]
    route = build_route([], count=3, wishlist=wishlist, no_meals=True)
    assert any(n["node_id"] == f"{WISH_NODE_PREFIX}1" for n in route)


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all passed")
