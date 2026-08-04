# ============================================================
# [v1] 결정 B/C 테스트 — 반경 0개 폴백(B) + 앵커 캡 제거(C)
# pipeline: AI 백엔드 / 시나리오 (테스트)
# 구현(요약): B=generator.generate_basic_scenario 빈노드 가드(위시 있으면 raise 안 함,
#            없으면 기존처럼 raise) / C=route_builder._select_count가 앵커를 count로
#            잘라내지 않음(앵커<=count 회귀도 함께 확인).
#            pytest 없이도 실행: `PYTHONPATH=. python tests/scenario/test_radius_edge.py`
# 구현일: 2026-07-14 | 작성: 정찬희 (radius-edge/jch/v1)
# ------------------------------------------------------------
# [v2] 네트워크 의존 제거 (2026-08-04, kys · test-offline/kys/v1)
#   '반경 내 0개'를 실제 TourAPI 호출로 재현하고 있었다. 외부 API가 느려지거나
#   응답 형식이 바뀌면 로직과 무관하게 테스트가 깨진다 — 실제로 base URL이 http라
#   타임아웃 나던 동안 이 파일만 20초씩 걸리며 실패했다(ai#43).
#   → TourAPI 호출부를 스텁으로 끊어 오프라인·결정론으로 만든다.
# ============================================================
import asyncio
import contextlib

from app.core.exceptions import DokkaebiAIError
from app.scenario import generator as _gen
from app.scenario.generator import generate_basic_scenario
from app.scenario.request import WishItem
from app.scenario.route_builder import _select_count

# 좌표는 이제 판정에 쓰이지 않는다(스텁이 항상 0개를 돌려줌). 의도를 남기려고 유지.
_FAR_X, _FAR_Y = 126.5311, 33.4996


@contextlib.contextmanager
def _tourapi_returns_nothing():
    """TourAPI를 '반경 내 0개'로 고정한다 — 네트워크 없이 결정론.

    pytest fixture 대신 컨텍스트 매니저를 쓰는 이유: 이 파일은 pytest 없이
    `python tests/scenario/test_radius_edge.py` 로도 돌아가야 한다(헤더 참고).
    """
    original = (_gen._tour.location_based_list, _gen._tour.detail_common)

    async def _empty(*_args, **_kwargs):
        return []

    async def _no_detail(*_args, **_kwargs):
        return None

    _gen._tour.location_based_list = _empty
    _gen._tour.detail_common = _no_detail          # overview 보강도 네트워크를 탄다
    try:
        yield
    finally:
        _gen._tour.location_based_list, _gen._tour.detail_common = original


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
    with _tourapi_returns_nothing():
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
        with _tourapi_returns_nothing():
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
