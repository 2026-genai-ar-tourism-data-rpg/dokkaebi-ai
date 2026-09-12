# ============================================================
# [v1] 회귀: 가고싶은 곳이 경로에 두 번 나오던 결함(조치계획 20260912 QA3)
# pipeline: AI 백엔드 / 시나리오 (테스트, 네트워크 0 — 실측 좌표만 고정 픽스처로 사용)
# 구현(요약): 실측 재현 = 출발 종묘 앞·반경 1km·위시 종묘(126510)에서
#            1번 wish_126510(종묘) / 2번 tour_126492(종묘광장공원, 67m)로 같은 자리가
#            두 칸을 차지했다. 원인은 (1) 위시 매칭이 content_id만 봤고 — 종묘 본체는
#            locationBasedList2에 아예 없어 매칭이 항상 실패한다 — (2) 중복 판정이
#            node_id만 봤기 때문. 좌표 매칭(wishlist v4) + 근접 중복 제거(route_builder v4)
#            두 곳을 함께 검증한다.
# 구현일: 2026-09-12 | 작성: pjh (wish-dupe-search-radius/pjh/v1)
# ============================================================
from app.scenario.request import WishItem
from app.scenario.route_builder import _select_count, build_route
from app.scenario.wishlist import WISH_NODE_PREFIX, select_wishlist_anchors

# 실측값(TourAPI 실키) — 같은 자리에 등록된 두 콘텐츠. 둘 사이 약 67m.
_JONGMYO = {"content_id": "126510", "name": "종묘 [유네스코 세계유산]",
            "lat": 37.5709802173, "lng": 126.9951311023}
_PLAZA = {"node_id": "tour_126492", "tour_content_id": "126492", "name": "종묘광장공원",
          "map_x": 126.9944166605, "map_y": 37.5711956572, "dist_m": 67.9}


def _far(nid: str, lat: float) -> dict:
    """종묘와 충분히 떨어진(수백 m 이상) 일반 후보."""
    return {"node_id": nid, "tour_content_id": nid.split("_")[-1], "name": nid,
            "map_x": 126.99, "map_y": lat, "dist_m": 500.0}


def _wish() -> WishItem:
    return WishItem(content_id=_JONGMYO["content_id"], name=_JONGMYO["name"],
                    lat=_JONGMYO["lat"], lng=_JONGMYO["lng"])


def test_content_id가_달라도_좌표가_가까우면_같은_장소로_본다():
    """종묘(126510) 위시 + 후보엔 종묘광장공원(126492)뿐 → 합성 앵커를 만들지 않는다."""
    anchors = select_wishlist_anchors([_PLAZA], [_wish()])

    assert len(anchors) == 1
    anchor = anchors[0]
    # 후보 노드를 채택했으므로 node_id가 후보 것 → 거리 채움 단계에서 중복될 수 없다.
    assert anchor["node_id"] == "tour_126492"
    assert not anchor["node_id"].startswith(WISH_NODE_PREFIX)
    assert anchor["out_of_radius"] is False


def test_좌표로_붙어도_사용자가_고른_이름과_원문키는_유지된다():
    """"종묘"를 골랐는데 "종묘광장공원"으로 바뀌어 나가면 안 된다(원문 조회 키도 위시 것)."""
    anchor = select_wishlist_anchors([_PLAZA], [_wish()])[0]

    assert anchor["name"] == _JONGMYO["name"]
    assert anchor["tour_content_id"] == _JONGMYO["content_id"]
    assert anchor["map_y"] == _JONGMYO["lat"] and anchor["map_x"] == _JONGMYO["lng"]


def test_경로에_같은_장소가_두_번_들어가지_않는다():
    """재현 시나리오 그대로: 위시 종묘 + 후보(종묘광장공원 포함) → 종묘 자리는 한 칸."""
    nodes = [_PLAZA, _far("tour_3019162", 37.575), _far("tour_2553876", 37.578)]

    route = build_route(nodes, count=4, start_x=_JONGMYO["lng"], start_y=_JONGMYO["lat"],
                        wishlist=[_wish()], no_meals=True)

    node_ids = [n["node_id"] for n in route]
    assert len(node_ids) == len(set(node_ids))
    # 종묘 자리(위시 앵커 + 종묘광장공원)가 합쳐져 한 칸만 남는다
    assert sum(1 for n in route if n["node_id"] in ("tour_126492", "wish_126510")) == 1
    assert [n for n in route if n["node_id"] == "tour_126492"][0]["name"] == _JONGMYO["name"]


def test_근접_후보를_건너뛰어도_노드_수는_유지된다():
    """중복은 '드롭'이 아니라 '건너뛰고 다음 후보' — 코스가 짧아지면 안 된다."""
    nodes = [_PLAZA, _far("tour_1", 37.575), _far("tour_2", 37.578), _far("tour_3", 37.581)]

    selected = _select_count(nodes, select_wishlist_anchors(nodes, [_wish()]), count=3)

    assert len(selected) == 3
    assert len({n["node_id"] for n in selected}) == 3


def test_멀리_떨어진_위시는_기존대로_합성_앵커다():
    """좌표 매칭은 100m 그물이다 — 반경 밖 위시(결정 B)는 그대로 합성 앵커로 살아난다."""
    wish = WishItem(content_id="999999", name="먼 곳", lat=37.60, lng=127.05)

    anchors = select_wishlist_anchors([_PLAZA], [wish])

    assert anchors[0]["node_id"] == f"{WISH_NODE_PREFIX}999999"
    assert anchors[0]["out_of_radius"] is True
