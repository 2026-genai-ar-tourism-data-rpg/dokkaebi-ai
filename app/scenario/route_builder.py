# ============================================================
# [v1] 노드 선택/배열 seam — build_route (앵커 강제포함 + 거리순 + 피날레 + 식음)
# pipeline: AI 백엔드 / 시나리오 (generator의 '노드 선택 단계'를 hook으로 분리)
# 구현(요약): 거리순 route = nodes[:count] 한 줄을 hook 가능한 파이프라인으로 추출.
#            기본 hook은 전부 no-op → 현재 거리순 동작 그대로 보존(behavior preserving).
#            각 단계는 오너별 별도 파일에서 구현 → generator.py 충돌 없이 병렬 작업.
#              · 위시 앵커(select_wishlist_anchors) = 이지선  (wishlist.py)
#              · 비인기 앵커(select_lowtraffic_anchors) = 박준형 (density.py)
#              · 식음 삽입(interleave_food)             = 정찬희 (food.py)
# 구현일: 2026-06-23 | 작성: kys (route-seam/kys/v1)
# ============================================================
from app.core.logger import get_logger
from app.scenario.density import select_lowtraffic_anchors
from app.scenario.wishlist import select_wishlist_anchors
from app.tourapi.client import haversine_m
from app.tourapi.food import interleave_food

logger = get_logger(__name__)


def build_route(
    nodes: list[dict], *, count: int,
    end_x: float | None = None, end_y: float | None = None,
    wishlist: list | None = None, budget: int | None = None,
    no_meals: bool = False, lowtraffic_k: int = 0,
) -> list[dict]:
    """[노드 선택/배열] 반경 내 거리순 후보(nodes) → 최종 방문 시퀀스(route).

    단계: ① 앵커 강제포함(위시+비인기) → ② 거리순 채우기(count개) →
          ③ 피날레(집 최근접) 맨 뒤 → ④ 식음 삽입(no_meals면 skip, 예산 게이팅).
    모든 hook이 기본 no-op이면 결과 = nodes[:count] + 피날레 배치(= 기존 동작).

    nodes: location_based_list 결과(이미 거리순, dist_m 포함). count: 기억석 조각 수.
    """
    # ① 앵커 수집 — 경로에 '반드시' 들어가야 하는 노드(위시리스트 + 비인기 샛길)
    anchors: list[dict] = []
    anchors += select_wishlist_anchors(nodes, wishlist or [])       # 이지선 hook
    if lowtraffic_k:
        anchors += select_lowtraffic_anchors(nodes, lowtraffic_k)   # 박준형 hook

    # ② 앵커 + 거리순으로 count개 채우기
    route = _fill_distance(nodes, anchors, count)

    # ③ 피날레: 끝점(집)에 가장 가까운 노드를 맨 뒤로 (출발→경유→집 동선)
    route = _place_finale(route, end_x, end_y)

    # ④ 식음(카페·식당) 삽입 — '밥 싫음'이면 통째로 skip, 아니면 예산 내에서
    if not no_meals:
        route = interleave_food(route, budget=budget)               # 정찬희 hook

    return route


def _fill_distance(nodes: list[dict], anchors: list[dict], count: int) -> list[dict]:
    """앵커를 먼저 확보하고 남은 슬롯을 거리순 후보로 채워 count개 선택.

    앵커 0개면 nodes[:count]와 동일(거리순). 최종은 dist_m 기준 재정렬로 동선 안정화.
    """
    selected: list[dict] = list(anchors)
    seen = {a["node_id"] for a in selected}
    for n in nodes:
        if len(selected) >= count:
            break
        if n["node_id"] not in seen:
            selected.append(n)
            seen.add(n["node_id"])
    # 앵커가 섞여도 가까운 순서로 돌도록 거리순 정렬(앵커 없으면 입력 순서 유지)
    selected.sort(key=lambda n: n.get("dist_m") if n.get("dist_m") is not None else 0.0)
    return selected[:count]


def _place_finale(route: list[dict], end_x: float | None, end_y: float | None) -> list[dict]:
    """끝점(집) 좌표가 있으면 그에 가장 가까운 노드를 피날레(맨 뒤)로 이동."""
    if end_x is None or end_y is None or len(route) <= 1:
        return route
    finale = min(route, key=lambda nd: haversine_m(end_y, end_x, nd["map_y"], nd["map_x"]))
    return [nd for nd in route if nd["node_id"] != finale["node_id"]] + [finale]
