# ============================================================
# [v1] 비인기 앵커 통합 검증 — select_lowtraffic_anchors 폴백/컷오프 + build_route 배선
# pipeline: AI 백엔드 / 시나리오 (테스트)
# 구현(요약): (1) 실데이터 결측(None/빈 rows/지역코드 없음) 시 [] 폴백 + build_route 무크래시,
#            (2) 절대 컷오프(density_lowtraffic_max_avg_rate) 초과 후보 제외,
#            (3) hubRank 카테고리 상대순위 재계산(호텔 등 타 카테고리가 순위 잠식 안 함) 검증,
#            (4) 선택된 low_traffic 노드가 build_route 전체 파이프라인(앵커선택→count선택→
#                NN정렬→피날레→식음삽입)을 거쳐도 최종 route에서 드롭되지 않는지 검증.
#            실 API 호출 없이 density.py가 참조하는 fetch_density_snapshot_sync /
#            fetch_concentration_by_name_sync를 module-level로 스와핑해서 검증.
#            pytest 없이도 실행: `PYTHONPATH=. python tests/scenario/test_lowtraffic.py`
# 구현일: 2026-07-13 | 작성: ljs (lowtraffic-tune/ljs/v1)
# ============================================================
import app.scenario.density as density
from app.config import get_settings
from app.scenario.density import select_lowtraffic_anchors
from app.scenario.route_builder import build_route


def _node(node_id: str, name: str, x: float, y: float, dist_m: float = 100.0) -> dict:
    return {"node_id": node_id, "name": name, "map_x": x, "map_y": y, "dist_m": dist_m}


def _cnctr_row(name: str, rate: float) -> dict:
    return {"tAtsNm": name, "cnctrRate": rate}


def _hub_row(name: str, rank: int, category: str = "관광지") -> dict:
    return {"hubTatsNm": name, "hubRank": rank, "hubCtgryLclsNm": category}


def _patch_density(fake_snapshot, fake_fallback=None):
    """density.py가 참조하는 벌크/개별 조회 함수를 실API 없이 교체하고 복원 함수를 반환."""
    orig_snapshot = density.fetch_density_snapshot_sync
    orig_fallback = density.fetch_concentration_by_name_sync
    density.fetch_density_snapshot_sync = fake_snapshot
    density.fetch_concentration_by_name_sync = fake_fallback or (lambda area_cd, signgu_cd, name: [])

    def _restore():
        density.fetch_density_snapshot_sync = orig_snapshot
        density.fetch_concentration_by_name_sync = orig_fallback

    return _restore


# ---------- 1. 실데이터 결측 시 폴백([]) ----------

def test_fallback_none_snapshot():
    restore = _patch_density(lambda region: None)
    try:
        result = select_lowtraffic_anchors([_node("a", "가", 127.0, 37.5)], k=2)
    finally:
        restore()
    assert result == []


def test_fallback_missing_area_code():
    restore = _patch_density(lambda region: {
        "concentration_rows": [_cnctr_row("가", 30.0)],
        "hub_rows": [_hub_row("가", 50)],
        "areaCd": None, "signguCd": None,
    })
    try:
        result = select_lowtraffic_anchors([_node("a", "가", 127.0, 37.5)], k=2)
    finally:
        restore()
    assert result == []


def test_fallback_empty_rows():
    restore = _patch_density(lambda region: {
        "concentration_rows": [], "hub_rows": [],
        "areaCd": "11", "signguCd": "11110",
    })
    try:
        result = select_lowtraffic_anchors([_node("a", "가", 127.0, 37.5)], k=2)
    finally:
        restore()
    assert result == []


def test_fallback_k_zero_or_no_nodes_skips_fetch():
    # k<=0/nodes 없음이면 조회 자체를 안 함(호출되면 실패하도록 함정 설치).
    def _boom(region):
        raise AssertionError("호출되면 안 됨 — k<=0/nodes=[]는 조회 전에 조기 반환해야 함")

    restore = _patch_density(_boom)
    try:
        assert select_lowtraffic_anchors([_node("a", "가", 127.0, 37.5)], k=0) == []
        assert select_lowtraffic_anchors([], k=2) == []
    finally:
        restore()


def test_build_route_survives_data_outage():
    # 실데이터 결측 상황에서도 build_route는 크래시 없이 count개를 정상 반환(거리순 폴백).
    restore = _patch_density(lambda region: None)
    try:
        nodes = [_node(f"s{i}", f"장소{i}", 127.0 + i * 0.001, 37.5, dist_m=i * 100.0) for i in range(5)]
        route = build_route(nodes, count=3, lowtraffic_k=2, no_meals=True)
    finally:
        restore()
    assert len(route) == 3
    assert not any(n.get("density_tier") == "low_traffic" for n in route)


# ---------- 2. 컷오프 — 절대 avg_cnctrRate ----------

def test_absolute_cutoff_excludes_high_rate():
    s = get_settings()
    below = s.density_lowtraffic_max_avg_rate - 5
    above = s.density_lowtraffic_max_avg_rate + 5
    restore = _patch_density(lambda region: {
        "concentration_rows": [_cnctr_row("한산한곳", below), _cnctr_row("혼잡한곳", above)],
        "hub_rows": [_hub_row("상관없음", 999)],  # select_lowtraffic_anchors는 hub_rows도 비어있으면 조기 반환함
        "areaCd": "11", "signguCd": "11110",
    })
    try:
        nodes = [_node("q", "한산한곳", 127.0, 37.5), _node("b", "혼잡한곳", 127.0, 37.5)]
        result = select_lowtraffic_anchors(nodes, k=2)
    finally:
        restore()
    assert [n["node_id"] for n in result] == ["q"]


# ---------- 3. hubRank — 카테고리 내 상대순위 ----------

def test_hub_rank_uses_category_relative_position():
    # 호텔(다른 카테고리)이 앞순위를 차지해도, allowed_category로 거른 뒤 재랭크하면
    # 실제 관광지 후보는 카테고리 내 상대순위 1위 → top_n 안에 들어 '중심 관광지'로 제외돼야 한다.
    s = get_settings()
    low_rate = s.density_lowtraffic_max_avg_rate - 10
    hub_rows = [_hub_row(f"호텔{i}", i, category="숙박") for i in range(1, 21)]
    hub_rows.append(_hub_row("실제관광지", 25, category="관광지"))
    restore = _patch_density(lambda region: {
        "concentration_rows": [_cnctr_row("실제관광지", low_rate)],
        "hub_rows": hub_rows,
        "areaCd": "11", "signguCd": "11110",
    })
    try:
        result = select_lowtraffic_anchors([_node("x", "실제관광지", 127.0, 37.5)], k=1)
    finally:
        restore()
    assert result == []


def test_hub_rank_allows_beyond_local_top_n():
    # 카테고리 내 상대순위가 top_n을 넘으면(진짜 변두리) 정상적으로 후보 가능.
    s = get_settings()
    low_rate = s.density_lowtraffic_max_avg_rate - 10
    hub_rows = [_hub_row(f"관광지{i}", i, category="관광지") for i in range(1, 21)]
    hub_rows.append(_hub_row("변두리명소", 21, category="관광지"))
    restore = _patch_density(lambda region: {
        "concentration_rows": [_cnctr_row("변두리명소", low_rate)],
        "hub_rows": hub_rows,
        "areaCd": "11", "signguCd": "11110",
    })
    try:
        result = select_lowtraffic_anchors([_node("y", "변두리명소", 127.0, 37.5)], k=1)
    finally:
        restore()
    assert [n["node_id"] for n in result] == ["y"]


# ---------- 4. build_route 통합 — 선택된 샛길이 최종 route에서 살아남는지 ----------

def test_selected_anchor_survives_full_pipeline():
    # 샛길명소는 거리상 맨 뒤(dist_m 큼) — 앵커 강제포함이 없으면 count=3 안에 못 든다.
    s = get_settings()
    low_rate = s.density_lowtraffic_max_avg_rate - 10
    restore = _patch_density(lambda region: {
        "concentration_rows": [_cnctr_row("샛길명소", low_rate)],
        "hub_rows": [_hub_row("상관없음", 999)],  # select_lowtraffic_anchors는 hub_rows도 비어있으면 조기 반환함
        "areaCd": "11", "signguCd": "11110",
    })
    try:
        nodes = [
            _node("near1", "근처1", 127.000, 37.500, dist_m=50.0),
            _node("near2", "근처2", 127.001, 37.500, dist_m=100.0),
            _node("near3", "근처3", 127.002, 37.500, dist_m=150.0),
            _node("far_anchor", "샛길명소", 127.010, 37.500, dist_m=900.0),
        ]
        route = build_route(
            nodes, count=3, start_x=126.999, start_y=37.500,
            end_x=126.999, end_y=37.500, lowtraffic_k=1, no_meals=True,
        )
    finally:
        restore()
    ids = [n["node_id"] for n in route]
    assert len(route) == 3
    assert "far_anchor" in ids
    anchor = next(n for n in route if n["node_id"] == "far_anchor")
    assert anchor.get("density_tier") == "low_traffic"


def test_selected_anchor_survives_food_step_call():
    # no_meals=False(식음 삽입 단계 통과)여도 앵커가 안 빠지는지. scenario_food_per_route
    # 기본값(0=OFF)에서 interleave_food는 route를 그대로 반환하는 계약이므로, 이 테스트는
    # '식음 단계를 거쳐도 앵커가 사라지지 않는다'를 그 계약 위에서 확인한다.
    s = get_settings()
    low_rate = s.density_lowtraffic_max_avg_rate - 10
    restore = _patch_density(lambda region: {
        "concentration_rows": [_cnctr_row("샛길명소", low_rate)],
        "hub_rows": [_hub_row("상관없음", 999)],  # select_lowtraffic_anchors는 hub_rows도 비어있으면 조기 반환함
        "areaCd": "11", "signguCd": "11110",
    })
    try:
        nodes = [
            _node("near1", "근처1", 127.000, 37.500, dist_m=50.0),
            _node("near2", "근처2", 127.001, 37.500, dist_m=100.0),
            _node("far_anchor", "샛길명소", 127.010, 37.500, dist_m=900.0),
        ]
        route = build_route(
            nodes, count=2, start_x=126.999, start_y=37.500, lowtraffic_k=1, no_meals=False,
        )
    finally:
        restore()
    assert "far_anchor" in [n["node_id"] for n in route]


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all passed")
