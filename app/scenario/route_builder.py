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
# ------------------------------------------------------------
# [v3] 좌표 결측 후보로 인한 500 수정 — 좌표 가드를 앵커에서 '후보 전체'로 확대.
# 구현(요약): v1 seam 가드가 앵커만 검사해서, TourAPI가 mapx/mapy를 비워 보낸 일반 후보가
#            _select_count로 들어오면 _nearest_neighbor/_path_len/_place_finale의
#            haversine_m(None, ...)에서 TypeError → 시나리오 생성 요청 전체가 500이 됐다.
#            (client._to_nodes는 mapx가 비면 map_x=None을 그대로 만든다.)
#            → 진입부에서 후보를 한 번 거르고, 앵커 가드는 합성 앵커용으로 유지.
#            위시 매칭 노드가 좌표 결측이면 위시 자체 좌표로 합성 앵커가 되어 오히려 살아난다.
#      + dist_m backfill을 backfill_dist_m()으로 분리(재사용 가능하게).
#        식음 삽입이 generator로 옮겨가면서 ⑥ backfill 뒤에 노드가 추가돼, 식음 노드만
#        dist_m=None으로 앱에 나가고 있었다 — generator가 삽입 후 한 번 더 호출한다.
# 구현일: 2026-08-12 | 작성: pjh (ai-logic-fix/pjh/v2)
# ------------------------------------------------------------
# [v4] 근접 중복 제거 — 같은 장소가 경로에 두 칸을 차지하던 결함(QA3) 경계 쪽.
# 구현(요약): 중복 판정이 node_id 동일성만 봤다. TourAPI가 한 장소를 여러 콘텐츠로
#            등록하면(실측: 종묘 126510 / 종묘광장공원 126492, 67m) node_id가 달라
#            둘 다 경로에 남고, 간격이 도착 인증 반경보다 좁아 한 자리에서 두 노드가
#            동시에 인증됐다. → 앵커 병합·거리 채움 모두에서 **좌표 근접**을 함께 본다.
#            임계값은 config.scenario_dupe_merge_m(기본 100m) 고정 — trigger_radius와
#            묶지 않는다(트리거를 다시 좁히면 중복이 조용히 되살아나기 때문).
#            채움 단계에서는 '드롭'이 아니라 '건너뛰고 다음 후보'라 노드 수는 유지된다.
# 구현일: 2026-09-12 | 작성: pjh (wish-dupe-search-radius/pjh/v1)
# 관련: 조치계획 20260912 QA3 · wishlist._coord_match(같은 결함의 앵커 쪽)
# ------------------------------------------------------------
# [v5] wishlist_only — 위시 앵커만으로 경로(거리순 채움·비인기 앵커 없음). 앱 위시리스트
#      '코스 생성'이 고른 장소로만 만들기 위함. 앵커가 좌표 결측으로 빠지면 그만큼 짧아진다.
# 구현일: 2026-09-19 | 작성: ljs (wishlist-only/ljs/v1)
# ============================================================
from app.config import get_settings
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
    no_meals: bool = False, lowtraffic_k: int = 0, wishlist_only: bool = False,
) -> list[dict]:
    """[노드 선택/배열] 반경 내 거리순 후보(nodes) → 최종 방문 시퀀스(route).

    단계: ① 앵커 강제포함(위시+비인기) → ② count개 선택 → ③ nearest-neighbor 동선 정렬
          → ④ 피날레(집 최근접) 맨 뒤 → ⑤ 식음 삽입(no_meals면 skip, 예산 게이팅).

    start_x/y(출발 좌표)를 주면 (1) dist_m 없는 앵커에 출발점 거리 backfill,
    (2) 단순 거리순이 아니라 '가까운 곳부터 이어 걷는' NN 동선으로 정렬한다.
    start_x/y가 없으면 기존 dist_m 순 폴백(behavior preserving).

    nodes: location_based_list 결과(이미 거리순, dist_m 포함). count: 기억석 조각 수.
    wishlist_only=True면 위시 앵커만으로 경로를 짠다 — 거리순 채움·비인기 앵커 없음(count 무시).
    """
    # ⓪ seam 가드: 좌표 없는 후보를 먼저 걸러 낸다. 앵커만 검사하던 v1 가드로는
    #    거리순 채움으로 들어온 좌표 결측 노드가 동선 정렬에서 그대로 터졌다(500).
    nodes = _placeable(nodes, what="후보")

    # ① 앵커 수집 — 경로에 '반드시' 들어가야 하는 노드(위시리스트 + 비인기 샛길)
    anchors: list[dict] = []
    anchors += select_wishlist_anchors(nodes, wishlist or [])       # 정찬희 hook
    if lowtraffic_k and not wishlist_only:
        anchors += select_lowtraffic_anchors(nodes, lowtraffic_k)   # 이지선 hook

    # seam 가드: 좌표(map_x/map_y) 없는 앵커는 동선 배치·거리계산 불가 → 드롭(500 방지).
    # (앱이 위시 좌표를 안 넘긴 경우 등. haversine None 크래시 예방 — kys 통합 책임)
    anchors = _placeable(anchors, what="앵커")

    # ② 앵커 + 가까운 후보로 count개 선택 — 위시 전용이면 채우지 않는다(고른 장소로만)
    route = _select_count(nodes, anchors, 0 if wishlist_only else count)

    # ③ 동선 정렬: 출발점→경유지→종료점 전체 비용을 기준으로 NN+2-opt 개선.
    route = _order_route(route, start_x, start_y, end_x, end_y)

    # 출발좌표가 없는 레거시 직접 호출만 기존 피날레 후처리를 유지한다.
    if start_x is None or start_y is None:
        route = _place_finale(route, end_x, end_y)

    # ⑤ 식음(카페·식당) 삽입 — '밥 싫음'이면 통째로 skip, 아니면 예산 내에서
    if not no_meals:
        route = interleave_food(route, budget=budget)               # 박준형 hook

    # ⑥ dist_m backfill(표시용) — 위시 합성앵커·TourAPI 누락 노드를 출발점 거리로.
    #    식음 노드는 generator가 이 뒤에 삽입하므로 거기서 한 번 더 호출한다.
    return backfill_dist_m(route, start_x, start_y)


def backfill_dist_m(
    route: list[dict], start_x: float | None, start_y: float | None,
) -> list[dict]:
    """dist_m이 비어 있는 노드에 출발점 기준 직선거리를 채운다(표시용, 제자리 수정).

    대상: 위시 합성 앵커(hook에 출발 좌표가 없어 None) · TourAPI dist 누락 ·
          generator가 나중에 삽입한 식음 노드. 출발 좌표가 없으면 no-op.
    """
    if start_x is None or start_y is None:
        return route
    for n in route:
        if n.get("dist_m") is None and n.get("map_x") is not None and n.get("map_y") is not None:
            n["dist_m"] = round(haversine_m(start_y, start_x, n["map_y"], n["map_x"]), 1)
    return route


def _merge_limit_m() -> int:
    """같은 지점으로 볼 거리(m). 설정 한 곳에서만 읽는다(매직넘버 금지)."""
    return get_settings().scenario_dupe_merge_m


def _same_spot(a: dict, b: dict, limit_m: int) -> bool:
    """두 노드가 사실상 같은 장소인지 — node_id가 같거나 좌표가 limit_m 안이면 True.

    TourAPI 중복 등록(종묘/종묘광장공원)처럼 id가 다른 같은 장소를 잡기 위한 판정이다.
    좌표가 없는 노드는 거리로 판정할 수 없어 id 비교만 한다(기존 동작 유지).
    """
    if a.get("node_id") == b.get("node_id"):
        return True
    if None in (a.get("map_x"), a.get("map_y"), b.get("map_x"), b.get("map_y")):
        return False
    return haversine_m(a["map_y"], a["map_x"], b["map_y"], b["map_x"]) <= limit_m


def _placeable(nodes: list[dict], *, what: str) -> list[dict]:
    """좌표(map_x/map_y)가 있는 노드만 남긴다 — 동선 배치·거리계산의 최소 전제.

    좌표가 없으면 haversine_m이 TypeError로 터져 시나리오 생성 요청 전체가 실패한다.
    한 노드 결측 때문에 코스를 통째로 못 만들 이유는 없으므로 드롭하고 WARN만 남긴다.
    """
    placeable = [n for n in nodes if n.get("map_x") is not None and n.get("map_y") is not None]
    dropped = len(nodes) - len(placeable)
    if dropped:
        logger.warning("좌표 결측 %s %d개 드롭(배치 불가)", what, dropped)
    return placeable


def _dedupe_anchors(anchors: list[dict]) -> list[dict]:
    """node_id가 같은 앵커를 하나로 병합한다.

    위시와 저혼잡 선택이 같은 장소를 동시에 고르면 경로에 중복 방문이 생길 수 있다.
    입력 순서는 유지하되 뒤 앵커의 부가 메타를 병합하고, wishlist source는 보존한다.
    """
    merged: dict[str, dict] = {}
    order: list[str] = []
    for anchor in anchors:
        node_id = anchor["node_id"]
        if node_id not in merged:
            merged[node_id] = dict(anchor)
            order.append(node_id)
            continue
        current = merged[node_id]
        combined = {**current, **anchor}
        if current.get("source") == "wishlist" or anchor.get("source") == "wishlist":
            combined["source"] = "wishlist"
        merged[node_id] = combined

    # 좌표 근접 병합(v4) — id가 달라도 같은 자리면 하나만 남긴다. 먼저 확정된 앵커를
    # 남기되(위시 입력 순서 보존), 위시 앵커가 나중에 와도 위시가 이긴다.
    limit = _merge_limit_m()
    kept: list[dict] = []
    for anchor in (merged[node_id] for node_id in order):
        twin = next((k for k in kept if _same_spot(k, anchor, limit)), None)
        if twin is None:
            kept.append(anchor)
            continue
        logger.info(
            "근접 앵커 병합: %s(%s) ↔ %s(%s) — 같은 지점(%dm 이내)",
            twin.get("node_id"), twin.get("name"),
            anchor.get("node_id"), anchor.get("name"), limit,
        )
        if anchor.get("source") == "wishlist" and twin.get("source") != "wishlist":
            kept[kept.index(twin)] = anchor
    return kept


def _select_count(nodes: list[dict], anchors: list[dict], count: int) -> list[dict]:
    """앵커를 먼저 확보하고 남은 슬롯을 가까운 후보(nodes는 이미 거리순)로 채워 count개 선택.

    선택만 담당 — 최종 방문 순서는 _order_route가 정한다(NN 동선).
    앵커가 count를 넘어도 전부 보존한다(결정 C) — 거리 채움만 count 도달 시 중단.

    v4: 이미 고른 노드와 **같은 자리**(node_id 동일 또는 좌표 근접)인 후보는 건너뛴다.
    앵커가 위시 장소를 이미 들고 있는데 그 옆에 붙은 다른 콘텐츠가 후보로 또 들어오면
    앱 화면에 같은 곳이 두 칸으로 찍히기 때문이다. 건너뛴 만큼 다음 후보로 채워
    노드 수(count)는 그대로 유지된다.
    """
    selected: list[dict] = _dedupe_anchors(anchors)
    seen = {a["node_id"] for a in selected}
    limit = _merge_limit_m()
    for n in nodes:
        if len(selected) >= count:
            break
        if n["node_id"] in seen:
            continue
        twin = next((sel for sel in selected if _same_spot(sel, n, limit)), None)
        if twin is not None:
            logger.info(
                "근접 후보 건너뜀: %s(%s) — 이미 선택된 %s(%s)와 같은 지점(%dm 이내)",
                n.get("node_id"), n.get("name"),
                twin.get("node_id"), twin.get("name"), limit,
            )
            seen.add(n["node_id"])
            continue
        selected.append(n)
        seen.add(n["node_id"])
    return selected


def _path_len(
    seq: list[dict], start_x: float, start_y: float,
    end_x: float | None = None, end_y: float | None = None,
) -> float:
    """출발점 → 경유지 → 종료점까지의 총 직선거리(m).

    종료점이 없으면 기존 열린 경로 비용을 유지한다.
    """
    total = 0.0
    px, py = start_x, start_y
    for n in seq:
        total += haversine_m(py, px, n["map_y"], n["map_x"])
        px, py = n["map_x"], n["map_y"]
    if end_x is not None and end_y is not None:
        total += haversine_m(py, px, end_y, end_x)
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


def _two_opt(
    seq: list[dict], start_x: float, start_y: float,
    end_x: float | None = None, end_y: float | None = None,
) -> list[dict]:
    """2-opt 개선: 구간을 뒤집어 총거리가 줄면 채택. NN의 국소 꼬임(교차)을 편다.

    열린 경로(출발점 고정, 복귀 없음) 기준. 노드 수가 적어(≈5~7) O(n²) 반복도 저렴.
    """
    best = list(seq)
    best_len = _path_len(best, start_x, start_y, end_x, end_y)
    improved = True
    while improved:
        improved = False
        for i in range(len(best) - 1):
            for j in range(i + 1, len(best)):
                cand = best[:i] + best[i:j + 1][::-1] + best[j + 1:]
                cand_len = _path_len(cand, start_x, start_y, end_x, end_y)
                if cand_len + 1e-6 < best_len:
                    best, best_len = cand, cand_len
                    improved = True
    return best


def _order_route(
    route: list[dict], start_x: float | None, start_y: float | None,
    end_x: float | None = None, end_y: float | None = None,
) -> list[dict]:
    """방문 순서 결정. 출발좌표 있으면 nearest-neighbor 초기해 → 2-opt로 개선,
    없으면 dist_m 순 폴백(dist_m 없는 노드는 맨 뒤).

    NN만으로는 '먼 곳으로 튀었다 되돌아오는' 꼬임이 남을 수 있어 2-opt로 근사 최적화한다.
    """
    if start_x is None or start_y is None or len(route) <= 1:
        return sorted(route, key=lambda n: n["dist_m"] if n.get("dist_m") is not None else float("inf"))
    return _two_opt(
        _nearest_neighbor(route, start_x, start_y),
        start_x, start_y, end_x, end_y,
    )


def _place_finale(route: list[dict], end_x: float | None, end_y: float | None) -> list[dict]:
    """끝점(집) 좌표가 있으면 그에 가장 가까운 노드를 피날레(맨 뒤)로 이동."""
    if end_x is None or end_y is None or len(route) <= 1:
        return route
    finale = min(route, key=lambda nd: haversine_m(end_y, end_x, nd["map_y"], nd["map_x"]))
    return [nd for nd in route if nd["node_id"] != finale["node_id"]] + [finale]
