# ============================================================
# [v1] 식음(카페·식당) — 예산/상권 쿠폰용 (현재 MOCK)
# pipeline: AI 백엔드 / 외부 데이터 (식음 노드 + 쿠폰)
# 구현(요약): ⚠️ MOCK. 실제는 TourAPI contentTypeId=39(음식점)/카카오 + 제휴 쿠폰(별도 task).
#            지금은 mock 카페·식당 목록 + 예상지출·쿠폰 → 예산 메커니즘(시나리오 MVP 예시) 자리만.
# 구현일: 2026-06-19 | 작성: kys (node-content/kys/v1)
# 관련: 기획 콘텐츠 스코프(관광지 우선, 식당/카페는 나중) · 시나리오_MVP_예시 §4 예산/쿠폰
# ============================================================

# (이름, 종류, 예상지출, 좌표 lat/lng) — 종로 mock
_MOCK_FOOD = [
    {"name": "익선동 한옥카페", "kind": "cafe", "spend": 5000, "map_y": 37.5742, "map_x": 126.9904},
    {"name": "인사동 전통찻집", "kind": "cafe", "spend": 6000, "map_y": 37.5740, "map_x": 126.9856},
    {"name": "광장시장 빈대떡", "kind": "food", "spend": 8000, "map_y": 37.5701, "map_x": 126.9997},
    {"name": "종로 국밥집", "kind": "food", "spend": 9000, "map_y": 37.5703, "map_x": 126.9880},
]


def nearby_food(map_x: float, map_y: float, budget: int | None = None, limit: int = 3) -> list[dict]:
    """[MOCK] 주변 식음 노드 + 상권 쿠폰. 실제는 contentTypeId=39/카카오 + 제휴.

    반환: [{name, kind, spend, coupon(다음 상권 쿠폰), map_x, map_y}]
    budget 주면 예상지출 합이 예산 이하인 것만(간단). 쿠폰은 mock 고정.
    """
    out = []
    total = 0
    for f in _MOCK_FOOD[:limit]:
        if budget is not None and total + f["spend"] > budget:
            continue
        total += f["spend"]
        out.append({**f, "coupon": {"to_kind": "food", "amount": 500}})
    return out


def interleave_food(route: list[dict], *, budget: int | None = None) -> list[dict]:
    """[STUB → 정찬희] 관광지 시퀀스(route) 사이사이에 카페/식당 노드 삽입. build_route ④ 단계 hook.

    route: 확정된 관광지 노드 시퀀스(거리순+피날레). budget: 예산(예상지출 합 게이팅).
    반환: 식음 노드가 끼워진 새 route. 지금은 route 그대로(no-op) → 기존 동작 보존.
    호출 측(build_route)에서 '밥 싫음(no_meals)'이면 아예 호출 안 함.

    TODO(정찬희):
      1) _MOCK_FOOD → TourAPI contentTypeId=39(음식점)/카카오 실데이터로 교체
      2) 노드 사이 위치(점심 시간대·동선 중간)에 nearby_food 결과를 예산 내에서 삽입
      3) ⚠️ 삽입한 식음 노드는 kind="food"/"cafe" 마커 필수 → generator._build_quest가
         '기억석 조각'으로 오인하지 않도록(fragment_id·is_finale 부여 제외) 분기 필요
    """
    return route
