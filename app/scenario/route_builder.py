# ============================================================
# [v1] 노드 선택/배열 seam — build_route (앵커 강제포함 + 거리순 + 피날레 + 식음)
# pipeline: AI 백엔드 / 시나리오 (generator의 '노드 선택 단계'를 hook으로 분리)
# 구현(요약): 거리순 route = nodes[:count] 한 줄을 hook 가능한 파이프라인으로 추출.
#            기본 hook은 전부 no-op → 현재 거리순 동작 그대로 보존(behavior preserving).
#            각 단계는 오너별 별도 파일에서 구현 → generator.py 충돌 없이 병렬 작업.
#              · 위시 앵커(select_wishlist_anchors) = 정찬희 (wishlist.py)
#              · 비인기 앵커(select_lowtraffic_anchors) = 이지선 (density.py)
#              · 식음 삽입(interleave_food)             = 박준형 (food.py)
# ------------------------------------------------------------
# [v2] 동선 개선 — 위시 앵커 dist_m backfill(먼 위시가 맨 앞 튀는 버그) +
#      단순 거리순 → nearest-neighbor 동선 정렬(지그재그 완화). start_x/y 필요.
# 구현일: 2026-07-06 | 작성: kys (route-nn/kys/v1)
# ============================================================
from app.core.logger import get_logger
from app.scenario.density import select_lowtraffic_anchors
from app.scenario.wishlist import select_wishlist_anchors
from app.tourapi.client import haversine_m
from app.tourapi.food import interleave_food

logger = get_logger(__name__)


def build_route(
    nodes: list[dict], *, count: int,
    start_x: float | None = None, start_y: float | None = None,
    end_x: float | None = None, end_y: float | None = None,
    wishlist: list | None = None, budget: int | None = None,
    no_meals: bool = False, lowtraffic_k: int = 0,
) -> list[dict]:
    """[노드 선택/배열] 반경 내 거리순 후보(nodes) → 최종 방문 시퀀스(route).

    단계: ① 앵커 강제포함(위시+비인기) → ② count개 선택 → ③ nearest-neighbor 동선 정렬
          → ④ 피날레(집 최근접) 맨 뒤 → ⑤ 식음 삽입(no_meals면 skip, 예산 게이팅).

    start_x/y(출발 좌표)를 주면 (1) dist_m 없는 앵커에 출발점 거리 backfill,
    (2) 단순 거리순이 아니라 '가까운 곳부터 이어 걷는' NN 동선으로 정렬한다.
    start_x/y가 없으면 기존 dist_m 순 폴백(behavior preserving).

    nodes: location_based_list 결과(이미 거리순, dist_m 포함). count: 기억석 조각 수.
    """
    # ① 앵커 수집 — 경로에 '반드시' 들어가야 하는 노드(위시리스트 + 비인기 샛길)
    anchors: list[dict] = []
    anchors += select_wishlist_anchors(nodes, wishlist or [])       # 정찬희 hook
    if lowtraffic_k:
        anchors += select_lowtraffic_anchors(nodes, lowtraffic_k)   # 이지선 hook

    # seam 가드: 좌표(map_x/map_y) 없는 앵커는 동선 배치·거리계산 불가 → 드롭(500 방지).
    # (앱이 위시 좌표를 안 넘긴 경우 등. haversine None 크래시 예방 — kys 통합 책임)
    placeable = [a for a in anchors if a.get("map_x") is not None and a.get("map_y") is not None]
    if len(placeable) < len(anchors):
        logger.warning("좌표 결측 앵커 %d개 드롭(배치 불가)", len(anchors) - len(placeable))
    anchors = placeable

    # ② 앵커 + 가까운 후보로 count개 선택
    route = _select_count(nodes, anchors, count)

    # ③ 동선 정렬: NN 초기해 → 2-opt 개선(출발점 기준). 없으면 dist_m 순 폴백
    route = _order_route(route, start_x, start_y)

    # ④ 피날레: 끝점(집)에 가장 가까운 노드를 맨 뒤로 (출발→경유→집 동선)
    route = _place_finale(route, end_x, end_y)

    # ⑤ 식음(카페·식당) 삽입 — '밥 싫음'이면 통째로 skip, 아니면 예산 내에서
    if not no_meals:
        route = interleave_food(route, budget=budget)               # 박준형 hook

    # ⑥ dist_m backfill(표시용) — 위시 합성앵커·TourAPI 누락·식음노드 전부 출발점 거리로.
    if start_x is not None and start_y is not None:
        for n in route:
            if n.get("dist_m") is None and n.get("map_x") is not None and n.get("map_y") is not None:
                n["dist_m"] = round(haversine_m(start_y, start_x, n["map_y"], n["map_x"]), 1)

    return route


def _select_count(nodes: list[dict], anchors: list[dict], count: int) -> list[dict]:
    """앵커를 먼저 확보하고 남은 슬롯을 가까운 후보(nodes는 이미 거리순)로 채워 count개 선택.

    선택만 담당 — 최종 방문 순서는 _order_route가 정한다(NN 동선).
    앵커가 count를 넘으면 앵커 우선으로 count개까지만.
    """
    selected: list[dict] = list(anchors)
    seen = {a["node_id"] for a in selected}
    for n in nodes:
        if len(selected) >= count:
            break
        if n["node_id"] not in seen:
            selected.append(n)
            seen.add(n["node_id"])
    return selected[:count]


def _path_len(seq: list[dict], start_x: float, start_y: float) -> float:
    """출발점 → seq 순서대로 이어 걸을 때 총 직선거리(m). 열린 경로(집 복귀 제외)."""
    total = 0.0
    px, py = start_x, start_y
    for n in seq:
        total += haversine_m(py, px, n["map_y"], n["map_x"])
        px, py = n["map_x"], n["map_y"]
    return total


def _nearest_neighbor(route: list[dict], start_x: float, start_y: float) -> list[dict]:
    """출발점에서 가장 가까운 노드 → 그 노드 기준 최근접 … 탐욕적 초기 동선."""
    remaining = list(route)
    ordered: list[dict] = []
    cx, cy = start_x, start_y                # 현재 위치(경도, 위도)
    while remaining:
        nxt = min(remaining, key=lambda n: haversine_m(cy, cx, n["map_y"], n["map_x"]))
        ordered.append(nxt)
        remaining.remove(nxt)
        cx, cy = nxt["map_x"], nxt["map_y"]
    return ordered


def _two_opt(seq: list[dict], start_x: float, start_y: float) -> list[dict]:
    """2-opt 개선: 구간을 뒤집어 총거리가 줄면 채택. NN의 국소 꼬임(교차)을 편다.

    열린 경로(출발점 고정, 복귀 없음) 기준. 노드 수가 적어(≈5~7) O(n²) 반복도 저렴.
    """
    best = list(seq)
    best_len = _path_len(best, start_x, start_y)
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                cand_len = _path_len(cand, start_x, start_y)
                if cand_len + 1e-6 < best_len:
                    best, best_len = cand, cand_len
                    improved = True
    return best


def _order_route(route: list[dict], start_x: float | None, start_y: float | None) -> list[dict]:
    """방문 순서 결정. 출발좌표 있으면 nearest-neighbor 초기해 → 2-opt로 개선,
    없으면 dist_m 순 폴백(dist_m 없는 노드는 맨 뒤).

    NN만으로는 '먼 곳으로 튀었다 되돌아오는' 꼬임이 남을 수 있어 2-opt로 근사 최적화한다.
    """
    if start_x is None or start_y is None or len(route) <= 2:
        return sorted(route, key=lambda n: n["dist_m"] if n.get("dist_m") is not None else float("inf"))
    return _two_opt(_nearest_neighbor(route, start_x, start_y), start_x, start_y)


def _place_finale(route: list[dict], end_x: float | None, end_y: float | None) -> list[dict]:
    """끝점(집) 좌표가 있으면 그에 가장 가까운 노드를 피날레(맨 뒤)로 이동."""
    if end_x is None or end_y is None or len(route) <= 1:
        return route
    finale = min(route, key=lambda nd: haversine_m(end_y, end_x, nd["map_y"], nd["map_x"]))
    return [nd for nd in route if nd["node_id"] != finale["node_id"]] + [finale]
