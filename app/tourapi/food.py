# ============================================================
# [v3] 식음(카페·식당) 삽입 + 예산 게이팅 — 구글 priceLevel 밴드 방식
# pipeline: AI 백엔드 / ① 선택 단계 마지막 (build_route ④ hook)
#
# 데이터 결론(v1~v2 시행착오의 정리):
#   업소별 "원화" 가격을 주는 합법·자동 소스는 한국에 없음. KOSIS는 지수(원화 아님),
#   참가격은 지역 평균(업소별 아님·API 없음). 그래서 "원화 추정" 자체를 폐기하고
#   구글 priceLevel(업소별 가격대 ₩~₩₩₩₩, 실데이터)로 "밴드 매칭"만 한다.
#   → 이 파일에 발명된 가격 수치 없음. 원 단위 spend_est 필드 폐지.
# ⚠️ 채택 조건부: scripts/measure_price_coverage.py 종로 보유율 실측 후 확정 (HANDOFF §6)
#
# 동작:
#   · 후보 = TourAPI 39 (키 없으면 mock) + google_places.attach_price_bands로 밴드 부착
#   · 게이팅 = 예산/인원 → 목표 밴드(경계는 config "정책값" — 데이터 주장 아님, 팀 조정)
#             후보 밴드 == 목표 최우선, 아래 밴드 허용(감점), 목표 초과 = 하드컷
#   · 인원수 = headcount (1인 예산 = budget/headcount → 목표 밴드 산출)
#   · 삽입 = 최장 구간 중간(식사), 차장 구간(카페) — v1 로직 유지
#   · 마커 = kind="food"/"cafe" + price_band (_build_quest 분기는 김예슬 공동 PR)
#   · 스위치 = settings.scenario_food_per_route (기본 0 = no-op, 기존 동작 보존)
# 구현일: 2026-07-04 | 작성: pjh (food-budget/pjh/v1) | v1 mock(kys) 폴백 유지
# ============================================================
import asyncio
from concurrent.futures import ThreadPoolExecutor

from app.config import get_settings
from app.core.logger import get_logger
from app.tourapi.google_places import BAND_LABEL

logger = get_logger(__name__)

# ------------------------------------------------------------
# 1. 분류 — cat3는 food/cafe "종류 구분"에만 사용 (가격 추정에 사용 안 함)
# ------------------------------------------------------------
_CAFE_CAT3 = {"A05020900"}             # 카페/전통찻집 (TourAPI 공식 분류)
_EXCLUDE_CAT3 = {"A05021000"}          # 클럽 — 게임 동선에 부적합 (구조 판단)

# config 병합 전 안전 폴백 (실값은 config.py — 매직넘버 단일 소스)
_DEFAULT_MIN_MEAL_TARGET_KRW = 4_000   # 식사 슬롯 성립 최소 1인 예산 (정책값)
_DEFAULT_MIN_CAFE_TARGET_KRW = 2_500   # 카페 슬롯 성립 최소 1인 예산 (정책값)
_DEFAULT_FOOD_SEARCH_RADIUS_M = 600
_DEFAULT_FOOD_FETCH_ROWS = 30
# 1인 예산 → 목표 밴드 경계 (⚠️ 정책값: 구글은 밴드의 원화 기준을 공개 안 함 → 팀이 정하는 규칙)
_DEFAULT_BAND1_MAX_KRW = 10_000        # 미만 = ₩
_DEFAULT_BAND2_MAX_KRW = 30_000        # 미만 = ₩₩
_DEFAULT_BAND3_MAX_KRW = 60_000        # 미만 = ₩₩₩, 이상 = ₩₩₩₩
_DEFAULT_UNKNOWN_BAND_SCORE = 1.5      # 밴드 미상 후보의 매칭 점수(1밴드 차이=1.0보다 약간 나쁨)


def _cfg(name: str, default):
    """config.py 조회 + getattr 안전접근(필드 병합 전에도 동작)."""
    return getattr(get_settings(), name, default)


# (이름, 종류, 가격대 밴드, 좌표) — 종로 mock. 키 없을 때 폴백.
# 밴드도 mock(데모용 가정값) — price_source="mock"으로 실데이터와 구분됨.
_MOCK_FOOD = [
    {"name": "익선동 한옥카페", "kind": "cafe", "band": 2, "map_y": 37.5742, "map_x": 126.9904},
    {"name": "인사동 전통찻집", "kind": "cafe", "band": 1, "map_y": 37.5740, "map_x": 126.9856},
    {"name": "광장시장 빈대떡", "kind": "food", "band": 1, "map_y": 37.5701, "map_x": 126.9997},
    {"name": "종로 국밥집",   "kind": "food", "band": 1, "map_y": 37.5703, "map_x": 126.9880},
    {"name": "인사동 한정식", "kind": "food", "band": 3, "map_y": 37.5720, "map_x": 126.9860},
]


# ------------------------------------------------------------
# 2. 순수 함수 — 예산→밴드, 밴드 매칭 (네트워크 0, 단위테스트 대상)
# ------------------------------------------------------------
def budget_to_band(budget_pp: float) -> int:
    """1인 예산 → 목표 가격대 밴드(1~4). 경계는 config 정책값."""
    if budget_pp < _cfg("food_band1_max_krw", _DEFAULT_BAND1_MAX_KRW):
        return 1
    if budget_pp < _cfg("food_band2_max_krw", _DEFAULT_BAND2_MAX_KRW):
        return 2
    if budget_pp < _cfg("food_band3_max_krw", _DEFAULT_BAND3_MAX_KRW):
        return 3
    return 4


def band_match_score(cand_band: int | None, target_band: int) -> float | None:
    """"예산대에 딱 맞는 급" 밴드 매칭 점수(낮을수록 좋음).

    · 목표 초과(cand > target) → None = 하드컷 (예산 밴드 위반)
    · 일치 → 0 / 한 밴드 아래 → 1 / 두 밴드 아래 → 2 ... (과소 페널티 = 가성비 편향 방지)
    · 미상(None) → 고정 점수(정책값 1.5): 일치 후보보단 밀리고, 두 밴드 아래보단 우선
    """
    if cand_band is None:
        return _cfg("food_unknown_band_score", _DEFAULT_UNKNOWN_BAND_SCORE)
    if cand_band > target_band:
        return None
    return float(target_band - cand_band)


def pick_candidate(cands: list[dict], kind: str, target_band: int,
                   exclude_ids: set) -> dict | None:
    """해당 kind 후보 중 목표 밴드에 가장 가까운 1개 선택. 없으면 None."""
    best, best_score = None, None
    for c in cands:
        if c.get("kind") != kind or c["node_id"] in exclude_ids:
            continue
        score = band_match_score(c.get("price_band"), target_band)
        if score is None:
            continue
        if best_score is None or score < best_score:
            best, best_score = c, score
    return best


def plan_slots(budget: int | None, headcount: int, per_route: int) -> list[str]:
    """예산·인원으로 삽입 슬롯 구성 결정 (식사/카페 다운그레이드 포함).

    · per_route>=2 → 식사1+카페1 / ==1 → 식사1
    · 1인 예산 < 식사 최소(정책값) → 카페로 다운그레이드 (MVP 예시=카페 only 코스 지원)
    · 카페 최소도 안 되면 [] (식음 0개 폴백 — 경로는 정상 진행)
    · budget=None → 게이팅 없이 기본 구성
    """
    if per_route <= 0:
        return []
    slots = ["food", "cafe"] if per_route >= 2 else ["food"]
    if budget is None:
        return slots
    budget_pp = budget / max(1, headcount)
    if budget_pp < _cfg("food_min_cafe_target_krw", _DEFAULT_MIN_CAFE_TARGET_KRW):
        return []
    if budget_pp < _cfg("food_min_meal_target_krw", _DEFAULT_MIN_MEAL_TARGET_KRW):
        return ["cafe"] * min(len(slots), 1)
    return slots


# ------------------------------------------------------------
# 3. 삽입 위치 — 동선 최장 구간 중간 (v1 그대로, 순수 좌표 수학)
# ------------------------------------------------------------
def _haversine_m(lat1, lng1, lat2, lng2) -> float:
    # route_builder와 동일 공식 — 순환 import 방지 위해 로컬 복제(작은 순수 함수)
    import math
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def gap_segments(route: list[dict]) -> list[tuple[float, int, float, float]]:
    """인접 노드 구간을 (거리, 삽입index, 중간lat, 중간lng)로 — 거리 내림차순.

    삽입index = i+1 (노드 i와 i+1 사이) → 피날레 '뒤' 삽입은 구조상 불가.
    """
    segs = []
    for i in range(len(route) - 1):
        a, b = route[i], route[i + 1]
        if None in (a.get("map_y"), a.get("map_x"), b.get("map_y"), b.get("map_x")):
            continue
        d = _haversine_m(a["map_y"], a["map_x"], b["map_y"], b["map_x"])
        segs.append((d, i + 1, (a["map_y"] + b["map_y"]) / 2, (a["map_x"] + b["map_x"]) / 2))
    segs.sort(key=lambda s: -s[0])
    return segs


# ------------------------------------------------------------
# 4. 후보 fetch — TourAPI 39 + 구글 밴드 부착 (키 없으면 mock)
# ------------------------------------------------------------
def _normalize_food_item(it: dict) -> dict | None:
    """locationBasedList2(39) item → 식음 후보 노드 (밴드는 아직 미부착)."""
    cat3 = it.get("cat3")
    if cat3 in _EXCLUDE_CAT3:
        return None
    return {
        "node_id": f"food_{it.get('contentid')}",
        "tour_content_id": it.get("contentid"),
        "name": it.get("title"),
        "map_x": float(it["mapx"]) if it.get("mapx") else None,
        "map_y": float(it["mapy"]) if it.get("mapy") else None,
        "addr1": it.get("addr1"), "cat3": cat3,
        "kind": "cafe" if cat3 in _CAFE_CAT3 else "food",
        "source": "TourAPI39",
    }


def _mock_candidates() -> list[dict]:
    """키 없음 폴백 — mock 밴드 포함(데모용), price_source="mock"으로 구분."""
    out = []
    for i, f in enumerate(_MOCK_FOOD):
        out.append({
            "node_id": f"food_mock_{i}", "tour_content_id": None,
            "name": f["name"], "map_x": f["map_x"], "map_y": f["map_y"],
            "addr1": None, "cat3": None, "kind": f["kind"],
            "price_band": f["band"], "price_band_label": BAND_LABEL[f["band"]],
            "price_source": "mock", "source": "mock",
        })
    return out


async def _fetch_candidates_async(map_x: float, map_y: float, radius_m: int) -> list[dict]:
    """TourAPI 39 실호출 → 구글 밴드 부착. (persist-on-touch 저장은 서버측)"""
    from app.tourapi.base import request              # 지연 import — mock 경로 네트워크 0
    from app.tourapi.google_places import attach_price_bands
    s = get_settings()
    result = await request(s.tourapi_base_url, "locationBasedList2", {
        "numOfRows": _cfg("food_fetch_rows", _DEFAULT_FOOD_FETCH_ROWS),
        "mapX": map_x, "mapY": map_y, "radius": radius_m,
        "contentTypeId": 39, "arrange": "E",
    })
    cands = [n for it in result["items"] if (n := _normalize_food_item(it))]
    return await attach_price_bands(cands)            # 캐시 hit이면 구글 호출 0


def _run_async(coro):
    """sync 컨텍스트(build_route)에서 async 호출 — 임시 브릿지.
    깔끔한 해법(generator에서 후보 미리 fetch해 주입)은 김예슬 공동 PR (HANDOFF §2)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(asyncio.run, coro).result()


def nearby_food(map_x: float, map_y: float, budget: int | None = None,
                limit: int = 10, radius_m: int | None = None) -> list[dict]:
    """주변 식음 후보 (밴드 부착 완료 상태로 반환). TourAPI 키 없으면 mock.

    budget 주면 1인 예산 밴드 초과 후보 제외(하드컷만 — 매칭은 caller).
    """
    s = get_settings()
    radius_m = radius_m if radius_m is not None else _cfg(
        "food_search_radius_m", _DEFAULT_FOOD_SEARCH_RADIUS_M)
    if s.tourapi_service_key:
        try:
            cands = _run_async(_fetch_candidates_async(map_x, map_y, radius_m))
        except Exception as e:            # 식음은 부가 기능 — 실패해도 시나리오를 막지 않음
            logger.warning("식음 후보 fetch 실패 → mock 폴백: %s", e)
            cands = _mock_candidates()
    else:
        logger.info("TourAPI 키 없음 → mock 식음 후보 사용")
        cands = _mock_candidates()
    if budget is not None:
        tb = budget_to_band(budget)
        cands = [c for c in cands
                 if c.get("price_band") is None or c["price_band"] <= tb]
    return cands[:limit]


# ------------------------------------------------------------
# 5. interleave_food — build_route ④ hook 본체
# ------------------------------------------------------------
def interleave_food(route: list[dict], *, budget: int | None = None,
                    headcount: int = 1, per_route: int | None = None,
                    candidates: list[dict] | None = None) -> list[dict]:
    """확정 동선(route) 사이에 카페/식당 노드 삽입 + 예산 밴드 게이팅.

    호출측(build_route) 계약: interleave_food(route, budget=budget) — 시그니처 호환 유지.
      · per_route: None이면 settings.scenario_food_per_route (기본 0 = no-op)
      · headcount: 인원수 — 1인 예산 = budget/headcount → 목표 밴드. 배선은 HANDOFF §3
      · candidates: 테스트용 주입. None이면 nearby_food로 fetch
    게이팅: 목표 밴드 초과 후보 하드컷, 일치 최우선, 아래 밴드 감점, 미상은 중간 점수.
    ⚠️ 밴드 데이터라 "원 단위 총액 합산 검증"은 정의상 불가 — 밴드 상한 + 슬롯 구성
       임계(정책값)로만 게이팅함을 명시. 앱 표시는 ₩~₩₩₩₩ 라벨(price_band_label).
    폴백: 예산 부족→카페 다운그레이드→0개(로그) — 경로 생성은 절대 실패시키지 않음.
    """
    s = get_settings()
    per_route = s.scenario_food_per_route if per_route is None else per_route
    if per_route <= 0 or len(route) < 2:
        return route                       # 스위치 OFF 또는 구간 없음 → 기존 동작 보존

    slots = plan_slots(budget, headcount, per_route)
    if not slots:
        logger.info("예산 %s원/%d인 — 식음 슬롯 성립 불가, 삽입 생략", budget, headcount)
        return route

    target_band = budget_to_band(budget / max(1, headcount)) if budget is not None else 2
    segs = gap_segments(route)
    if not segs:
        return route

    picked: list[tuple[int, dict]] = []    # (삽입index, 노드)
    used_ids = {n["node_id"] for n in route}
    for slot_i, kind in enumerate(slots):
        _d, ins_idx, mid_lat, mid_lng = segs[min(slot_i, len(segs) - 1)]
        cands = candidates if candidates is not None else nearby_food(mid_lng, mid_lat)
        choice = pick_candidate(cands, kind, target_band, used_ids)
        if choice is None and kind == "food":          # 식사 후보 없음 → 카페 다운그레이드
            choice = pick_candidate(cands, "cafe", target_band, used_ids)
        if choice is None:
            continue
        used_ids.add(choice["node_id"])
        node = {**choice, "coupon": {"to_kind": "food", "amount": 500}}   # 상권 쿠폰(mock 유지)
        picked.append((ins_idx, node))

    if not picked:
        logger.info("예산 %s원/%d인 목표밴드 %s 후보 없음 — 삽입 생략",
                    budget, headcount, BAND_LABEL.get(target_band))
        return route

    new_route = list(route)
    for ins_idx, node in sorted(picked, key=lambda p: -p[0]):
        new_route.insert(ins_idx, node)    # index 큰 것부터 → 앞 삽입이 뒤를 안 밀게
    logger.info("식음 %d개 삽입 (목표밴드 %s, %d인, 예산 %s원): %s",
                len(picked), BAND_LABEL.get(target_band), max(1, headcount), budget,
                [f"{n['name']}({n.get('price_band_label')})" for _, n in picked])
    return new_route

async def nearby_food_async(map_x: float, map_y: float, budget: int | None = None,
                            limit: int = 10, radius_m: int | None = None) -> list[dict]:
    """async generator용 후보 조회. 실행 중인 이벤트 루프를 동기 대기시키지 않는다."""
    s = get_settings()
    radius_m = radius_m if radius_m is not None else _cfg(
        "food_search_radius_m", _DEFAULT_FOOD_SEARCH_RADIUS_M)
    if s.tourapi_service_key:
        try:
            cands = await _fetch_candidates_async(map_x, map_y, radius_m)
        except Exception as e:
            logger.warning("식음 후보 fetch 실패 → mock 폴백: %s", e)
            cands = _mock_candidates()
    else:
        logger.info("TourAPI 키 없음 → mock 식음 후보 사용")
        cands = _mock_candidates()
    if budget is not None:
        target_band = budget_to_band(budget)
        cands = [c for c in cands
                 if c.get("price_band") is None or c["price_band"] <= target_band]
    return cands[:limit]


async def interleave_food_async(route: list[dict], *, budget: int | None = None,
                                headcount: int = 1,
                                per_route: int | None = None) -> list[dict]:
    """비동기 시나리오 생성 경로용 식음 삽입.

    후보 조회를 ``await``하여 ``ThreadPoolExecutor(...).result()``로 이벤트 루프를
    막지 않는다. 기존 동기 ``interleave_food``는 직접 호출 호환을 위해 유지한다.
    """
    s = get_settings()
    per_route = s.scenario_food_per_route if per_route is None else per_route
    if per_route <= 0 or len(route) < 2:
        return route

    slots = plan_slots(budget, headcount, per_route)
    if not slots:
        return route
    target_band = budget_to_band(budget / max(1, headcount)) if budget is not None else 2
    segs = gap_segments(route)
    if not segs:
        return route

    candidate_groups = await asyncio.gather(*[
        nearby_food_async(
            segs[min(slot_i, len(segs) - 1)][3],
            segs[min(slot_i, len(segs) - 1)][2],
        )
        for slot_i in range(len(slots))
    ])

    picked: list[tuple[int, dict]] = []
    used_ids = {n["node_id"] for n in route}
    for slot_i, kind in enumerate(slots):
        _d, ins_idx, _mid_lat, _mid_lng = segs[min(slot_i, len(segs) - 1)]
        cands = candidate_groups[slot_i]
        choice = pick_candidate(cands, kind, target_band, used_ids)
        if choice is None and kind == "food":
            choice = pick_candidate(cands, "cafe", target_band, used_ids)
        if choice is None:
            continue
        used_ids.add(choice["node_id"])
        picked.append((ins_idx, {
            **choice,
            "coupon": {"to_kind": "food", "amount": 500},
        }))

    if not picked:
        return route
    new_route = list(route)
    for ins_idx, node in sorted(picked, key=lambda pair: -pair[0]):
        new_route.insert(ins_idx, node)
    return new_route
