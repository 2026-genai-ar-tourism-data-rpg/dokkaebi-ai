# 식음(카페·식당) 삽입 + 예산 게이팅

## 1. 작업 개요

상위 Task: WEEKLY-PLAN §2 — ① 식음 삽입 + 예산 게이팅
작업 브랜치: `food-budget/pjh/v1`
영역: AI / Scenario

경로 생성 시 확정된 관광지 동선 사이에, **입력된 예산·인원수에 맞는 가격대의 카페/식당 노드를 삽입**하는 기능을 구현했다.

기존 `food.py`의 `nearby_food` / `interleave_food` STUB을 실제 데이터 기반 로직으로 대체했다.

---

## 2. 수정 파일

```text
app/tourapi/food.py           (STUB → 구현)
app/tourapi/google_places.py  (신규)
app/config.py                 (식음·Google 설정 추가)
.env.example                  (항목 2개 추가)
scripts/measure_price_coverage.py  (신규 — 커버리지 실측)
tests/test_food.py            (신규 — 14개)
```

수정하지 않은 파일:

```text
app/scenario/generator.py
app/scenario/route_builder.py
app/tourapi/base.py
```

`build_route`는 이미 `interleave_food(route, budget=budget)`를 호출하고 있으므로, 이번 작업은 `food.py` 내부 구현으로 처리했다. `generator._build_quest`의 식음 노드 분기는 김예슬과 공동 PR로 조율한다 (→ `HANDOFF-food-budget.md`).

---

## 3. 전체 흐름

```text
generate_basic_scenario()
  → build_route(nodes, budget=...)
  → ①~③ 관광지 route 확정 (앵커·거리순·피날레)
  → ④ interleave_food(route, budget=budget)
  → plan_slots: 예산/인원 → 슬롯 구성 (식사+카페 / 카페만 / 없음)
  → budget_to_band: 1인 예산 → 목표 가격대 밴드(₩~₩₩₩₩)
  → nearby_food: TourAPI 39 후보 + Google priceLevel 밴드 부착
  → pick_candidate: 목표 밴드 일치 최우선 매칭
  → 동선 최장 구간 중간에 삽입, kind="food"/"cafe" 마커 부여
  → route 확정
```

---

## 4. 사용한 외부 API

| 목적           | 서비스                                                | 주요 필드                                 |
| -------------- | ----------------------------------------------------- | ----------------------------------------- |
| 식당·카페 후보 | `KorService2 / locationBasedList2 (contentTypeId=39)` | `title`, `mapx/mapy`, `cat3`, `contentid` |
| 업소별 가격대  | `Google Places API (New) / places:searchText`         | `priceLevel` (₩~₩₩₩₩ 4단계)               |

`cat3`는 food/cafe **종류 구분에만** 사용한다 (`A05020900`=카페, `A05021000`=클럽 제외). 가격 추정에는 사용하지 않는다.

---

## 5. 가격 데이터 조사 결론 (왜 "밴드" 방식인가)

업소별 **원화** 가격을 주는 합법·자동 데이터 소스는 국내에 존재하지 않음을 확인했다.

```text
TourAPI / 카카오 / 네이버 API  → 가격 필드 자체가 없음
KOSIS 소비자물가              → 지수(2020=100)이지 원화가 아님 → 가격으로 사용 불가
참가격/지방물가 외식비          → 원화 실측이지만 지역 평균(업소별 아님) + API 없음(웹 화면만)
착한가격업소                   → 업소별 실가격이지만 저가 지정업소만 → 예산 상한 매칭에 부적합
네이버플레이스 크롤링            → 데이터는 있으나 약관 위반 → 공모전 출품작에서 사용 불가
```

따라서 "원화 추정"을 포기하고, 업소별 **가격대(₩~₩₩₩₩)를 실데이터로 제공하는 Google priceLevel** 기반 밴드 매칭으로 확정했다. 코드에 추정·발명된 가격 수치는 없다.

⚠️ **채택 조건부**: Google의 국내 priceLevel 커버리지는 미검증이다. `scripts/measure_price_coverage.py`로 종로 후보 보유율을 실측한 뒤 최종 확정한다 (판정 가이드: 50% 미만이면 폐기 후 참가격 카테고리 평균 방식으로 회귀).

---

## 6. 예산 게이팅 기준

### 6.1 예산 → 목표 밴드

1인 예산(`budget / headcount`)을 목표 밴드로 변환한다. 경계는 **정책값**이다 — Google이 priceLevel의 원화 기준을 공개하지 않으므로, `trigger_radius`처럼 팀이 정하고 조정하는 규칙이다.

```python
food_band1_max_krw: int = 10000   # 미만 = ₩
food_band2_max_krw: int = 30000   # 미만 = ₩₩
food_band3_max_krw: int = 60000   # 미만 = ₩₩₩, 이상 = ₩₩₩₩
```

### 6.2 밴드 매칭 ("예산대에 딱 맞는 급")

```text
후보 밴드 == 목표 밴드 → 점수 0 (최우선)
후보 밴드 <  목표 밴드 → 점수 = 차이 (허용하되 감점 — 가성비 편향 방지)
후보 밴드 >  목표 밴드 → 하드컷 (예산 초과 후보는 절대 선택 안 함)
밴드 미상(None)        → 점수 1.5 (일치보단 밀리고 2단계 아래보단 우선)
```

### 6.3 슬롯 구성·다운그레이드

```text
per_route >= 2 → 식사 1 + 카페 1
1인 예산 < 4,000원(정책값) → 식사 포기, 카페만
1인 예산 < 2,500원(정책값) → 식음 0개 (경로는 정상 생성)
budget=None → 게이팅 없이 기본 구성
```

같은 총예산이라도 인원이 많으면 1인 예산이 줄어 목표 밴드·슬롯이 자동으로 내려간다.

### 6.4 삽입 위치

```text
식사 = 동선에서 인접 노드 간 거리가 가장 긴 구간의 중간점 근처
카페 = 두 번째로 긴 구간
삽입 index = i+1 (노드 사이) → 피날레 '뒤' 삽입은 구조상 불가
```

---

## 7. 호출 방식

Google priceLevel은 업소별로 거의 변하지 않으므로 캐시를 전제로 설계했다.

```python
google_price_cache_ttl_s: int = 604800   # 7일 (tourapi overview 캐시와 동일 패턴)
google_places_semaphore: int = 5         # 동시 조회 상한
```

첫 조회 이후 같은 업소는 캐시 hit으로 Google 호출이 0이 된다. 파일럿 볼륨(종로 수백 업소 × 1회)은 Pro SKU 무료 상한(월 5,000콜) 안이다.

`build_route`(sync) 안에서 async 클라이언트를 호출하기 위해 스레드 격리 루프(`_run_async`)를 임시 브릿지로 사용한다. 깔끔한 해법(generator async 구간에서 후보 선조회 후 주입)은 `interleave_food(candidates=)`로 이미 받을 수 있게 해뒀고, 배선은 공동 PR로 처리한다.

---

## 8. 폴백 체계

어떤 실패도 시나리오 생성을 막지 않는다.

```text
TourAPI 키 없음        → mock 종로 후보 5곳 (밴드 포함, price_source="mock")
Google 키 없음         → 밴드 미상 처리 (호출 자체를 안 함)
Google 조회 실패        → 해당 업소만 미상 처리
목표 밴드 후보 없음      → 식사→카페 다운그레이드 → 0개 (로그)
스위치 OFF(기본)        → 완전 no-op — 기존 route 그대로
```

---

## 9. 주요 함수

### `budget_to_band(budget_pp)`

1인 예산 → 목표 밴드(1~4). 경계는 config 정책값.

### `band_match_score(cand_band, target_band)`

밴드 매칭 점수(낮을수록 좋음). 초과=None(하드컷), 일치=0, 아래=차이, 미상=1.5.

### `plan_slots(budget, headcount, per_route)`

슬롯 구성 결정. 다운그레이드/0개 폴백 포함.

### `nearby_food(map_x, map_y, budget=None, ...)`

TourAPI 39 후보 + 밴드 부착 완료 상태로 반환. budget 주면 초과 밴드 하드컷.

### `interleave_food(route, *, budget, headcount=1, per_route=None, candidates=None)`

본체. 호출측 계약(`interleave_food(route, budget=budget)`) 유지 — 신규 인자는 전부 기본값 있음.

### `google_places.fetch_price_band(name, lat, lng)` / `attach_price_bands(cands)`

업소 1곳 / 후보 리스트의 priceLevel 조회 (캐시·세마포어).

---

## 10. 설정값

```python
# 스위치 (기본 0 = OFF, 기존 동작 100% 보존)
scenario_food_per_route: int = 0

# 식음 게이팅 (전부 정책값 — env로 무코드 튜닝)
food_min_meal_target_krw: int = 4000
food_min_cafe_target_krw: int = 2500
food_search_radius_m: int = 600
food_fetch_rows: int = 30
food_band1_max_krw / band2 / band3
food_unknown_band_score: float = 1.5

# Google Places (키는 .env로만 주입 — llm_api_key와 동일 패턴)
google_maps_api_key: str = ""
google_places_timeout / semaphore / cache_ttl_s
```

---

## 11. 실행 방법

```bash
# .env (레포 루트 — 커밋 금지)
DOKKAEBI_SCENARIO_FOOD_PER_ROUTE=2
DOKKAEBI_TOURAPI_SERVICE_KEY=...        # 없으면 mock 후보로 동작
DOKKAEBI_GOOGLE_MAPS_API_KEY=...        # 없으면 가격대 미상 처리

# 단위테스트 (네트워크 0, 키 없이 통과)
python -m pytest tests/test_food.py -q

# 커버리지 실측 (Google 방식 채택 판정용 — 키 필요)
python scripts/measure_price_coverage.py --limit 30
```

터미널 확인:

```bash
python - <<'PY'
import asyncio, os
os.environ["DOKKAEBI_SCENARIO_FOOD_PER_ROUTE"] = "2"
from app.config import get_settings; get_settings.cache_clear()
from app.scenario.route_builder import build_route
from app.tourapi.client import TourAPIClient

async def main():
    nodes = await TourAPIClient().location_based_list(126.9854, 37.5766, 2000)
    r = build_route(nodes, count=3, end_x=126.9769, end_y=37.5759, budget=20000)
    for n in r:
        tag = f"[{n['kind']}]" if n.get("kind") else "[poi ]"
        print(tag, n["name"], n.get("price_band_label", ""))

asyncio.run(main())
PY
```

---

## 12. 검증 결과

단위테스트 14개 통과 (골든 = 시나리오*MVP*예시 §0: 안국역·예산 20,000원, 인원수 변수화).

mock 기준 통합 확인 — 예산이 실제로 선택을 바꾼다:

| 입력            | 목표 밴드 | 삽입 결과                                |
| --------------- | --------- | ---------------------------------------- |
| 20,000원 · 1인  | ₩₩        | 광장시장 빈대떡(₩) + 익선동 한옥카페(₩₩) |
| 150,000원 · 1인 | ₩₩₩₩      | 인사동 한정식(₩₩₩) + 익선동 한옥카페(₩₩) |
| 20,000원 · 6인  | ₩         | 카페만 (식사 다운그레이드)               |
| 2,000원 · 4인   | —         | 식음 0개, 경로는 정상                    |
| 스위치 OFF      | —         | 기존 route와 완전 동일 (no-op)           |

Google 실호출 성능·커버리지는 키 확보 후 측정 예정 (미측정 상태 — 실측 전 수치 주장 안 함).

---

## 13. 한계 및 추후 개선

현재 한계:

```text
- Google priceLevel 국내 커버리지 미검증 → 커버리지 실측이 채택의 선행 조건
- 밴드 데이터 특성상 "원 단위 총액 합산 검증"은 정의상 불가 (밴드 상한 + 슬롯 임계로만 게이팅)
- headcount·candidates 주입은 구현돼 있으나 배선 전 (기본 headcount=1로 동작)
- 예산→밴드 경계는 정책값 — 데모 돌려보며 팀 조정 필요
- _build_quest 분기 전에는 식음 노드가 기억석 조각으로 오인될 수 있음 (머지 전 필수 조율)
```

추후 개선:

```text
- generator async 구간에서 후보 선조회 → interleave_food(candidates=) 주입 (스레드 브릿지 제거)
- request.py에 headcount 정식 필드 추가 → 인원수 배선
- 플레이어 방문 인증 시 지출 신고 수집 → 자체 실측 가격 데이터 축적 (공모전 발전방향)
- 커버리지 미달 시: 참가격 카테고리 평균(한식·중식만 실측 가능) 방식으로 회귀
```
