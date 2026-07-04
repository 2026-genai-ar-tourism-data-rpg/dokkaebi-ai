# 비인기 앵커 선택 로직

## 1. 작업 개요

상위 Task: `2026-genai-ar-tourism-data-rpg/.github/issues/4`  
작업 브랜치: `lowtraffic-select/ljs/v1`  
영역: AI / Scenario

경로 생성 시 거리순 관광지만 선택하던 기존 방식에, TourAPI BigData 기반으로 **사람이 상대적으로 적은 숨은 명소**를 섞어 넣는 기능을 구현했다.

기존 `density.py`의 비인기 앵커 선택 STUB을 실제 데이터 기반 로직으로 대체했다.

---

## 2. 수정 파일

```text
app/config.py
app/tourapi/bigdata.py
app/scenario/density.py
```

수정하지 않은 파일:

```text
app/scenario/generator.py
app/scenario/route_builder.py
app/tourapi/base.py
```

`generator.py`는 이미 `build_route(..., lowtraffic_k=s.scenario_lowtraffic_anchors)`를 호출하고 있으므로, 이번 작업에서는 `density.py`의 `select_lowtraffic_anchors()`를 구현하는 방식으로 처리했다.

---

## 3. 전체 흐름

```text
generate_basic_scenario()
  → TourAPI location_based_list로 반경 내 관광지 후보 수집
  → build_route(nodes, lowtraffic_k=...)
  → select_lowtraffic_anchors(nodes, k)
  → BigData 기반 비인기 후보 선택
  → 선택 node에 density_tier="low_traffic" 부여
  → route 확정
  → density_label()로 최종 density_tier 반영
```

---

## 4. 사용한 BigData API

| 목적 | 서비스 | 주요 필드 |
|---|---|---|
| 관광지 집중률 | `TatsCnctrRateService / tatsCnctrRatedList` | `tAtsNm`, `baseYmd`, `cnctrRate` |
| 중심 관광지 랭킹 | `LocgoHubTarService1 / areaBasedList1` | `hubTatsNm`, `hubRank`, `hubCtgryLclsNm`, `mapX`, `mapY` |

이번 MVP에서는 `TarRlteTarService1`, `DataLabService`는 사용하지 않는다.

---

## 5. 지역 설정

MVP는 종로 기준으로 동작한다.

```python
density_default_region: str = "종로"

density_region_code_map: dict[str, dict[str, str]] = {
    "종로": {"areaCd": "11", "signguCd": "11110"}
}
```

추후 지역 확장 시 `density_region_code_map`에 지역별 `areaCd`, `signguCd`를 추가하면 된다.

---

## 6. 비인기 앵커 선택 기준

### 6.1 집중률

`TatsCnctrRateService`에서 관광지별 `cnctrRate`를 가져오고, 장소별 평균값을 계산한다.

```text
avg_cnctrRate = 관광지별 cnctrRate 평균
```

평균 `cnctrRate`가 낮을수록 더 한산한 후보로 본다.

### 6.2 중심 관광지 제외

`LocgoHubTarService1`의 `hubRank`를 사용한다.

```text
hubRank <= 20 → 중심 관광지로 보고 제외
hubRank > 20  → 비인기 후보 가능
hub row 없음  → 상위 중심 관광지는 아닌 것으로 보고 후보 가능
```

설정값:

```python
density_hub_popular_top_n: int = 20
```

### 6.3 최종 정렬

```text
1. avg_cnctrRate 낮은 순
2. hubRank가 있으면 숫자가 큰 순
3. dist_m 가까운 순
```

---

## 7. 호출 방식

이번 구현은 아래 구조를 사용한다.

```text
B. 지역 벌크 조회
+
C. 모듈 레벨 TTL 캐시
+
A. 제한적 targeted fallback
```

### 기본: 벌크 조회

node마다 API를 호출하지 않고, 종로 지역 BigData를 한 번에 가져온다.

```python
density_cnctr_num_of_rows: int = 1000
density_hub_num_of_rows: int = 100
```

종로 실측 기준 concentration row는 약 3,390건이며, `numOfRows=1000`이면 약 4페이지 안에서 전체 수집이 가능했다.

### 캐시

BigData snapshot은 모듈 레벨 TTL 캐시에 저장한다.

```python
density_bigdata_cache_ttl_s: int = 21600  # 6시간
```

첫 호출 이후 같은 프로세스 안에서는 API를 다시 호출하지 않고 캐시를 사용한다.

### fallback

벌크 매칭에 실패한 node만 제한적으로 관광지명 개별 조회를 시도한다.

```python
density_targeted_fallback_limit: int = 3
density_targeted_num_of_rows: int = 30
```

fallback 결과도 이름 단위로 캐시한다.

---

## 8. 장소명 매칭

API 요청/응답 key는 원본 그대로 사용한다.

```text
tAtsNm
hubTatsNm
cnctrRate
hubRank
areaCd
signguCd
```

단, 장소명 value 비교에는 정규화를 사용한다.

```text
node["name"]
row["tAtsNm"]
row["hubTatsNm"]
```

정규화는 비교용으로만 사용하고, 원본 row를 변경하지 않는다.

예시:

```text
"서울 운현궁" → "서울운현궁"
"창덕궁과 후원 [유네스코 세계유산]" → "창덕궁과후원"
```

---

## 9. 주요 함수

### `density_label(node)`

이미 `density_tier`가 있으면 유지하고, 없으면 `"popular"`를 반환한다.

```text
low_traffic → 유지
popular → 유지
없음 → popular
```

### `select_lowtraffic_anchors(nodes, k)`

비인기 앵커를 최대 `k`개 선택한다.

```text
1. BigData snapshot 조회
2. concentration row 매칭
3. cnctrRate 평균 계산
4. hubRank <= 20 후보 제외
5. 후보 정렬
6. 상위 k개 node에 density_tier="low_traffic" 부여
7. 선택된 node 리스트 반환
```

실데이터가 없거나 API 실패 시에는 빈 리스트를 반환한다.

---

## 10. 주요 설정값

```python
scenario_lowtraffic_anchors: int = 0

density_default_region: str = "종로"
density_region_code_map: dict[str, dict[str, str]] = {
    "종로": {"areaCd": "11", "signguCd": "11110"}
}

density_hub_popular_top_n: int = 20
density_allowed_hub_category: str = "관광지"

density_cnctr_num_of_rows: int = 1000
density_cnctr_max_pages: int = 20
density_hub_num_of_rows: int = 100
density_hub_max_pages: int = 20
density_hub_base_months_ago: int = 3

density_candidate_limit: int = 20
density_targeted_fallback_limit: int = 3
density_targeted_num_of_rows: int = 30

density_bigdata_cache_ttl_s: int = 21600
```

`scenario_lowtraffic_anchors` 의미:

```text
0 → 기존 거리순 동작 유지
1 이상 → 비인기 앵커 선택 시도
```

---

## 11. 로컬 테스트

### 문법 확인

```bash
python -m py_compile \
  app/config.py \
  app/tourapi/bigdata.py \
  app/scenario/density.py
```

### BigData snapshot 확인

```bash
python - <<'PY'
from app.tourapi.bigdata import fetch_density_snapshot_sync

snapshot = fetch_density_snapshot_sync("종로")

print("snapshot exists =", bool(snapshot))
if snapshot:
    print("concentration rows =", len(snapshot.get("concentration_rows") or []))
    print("hub rows =", len(snapshot.get("hub_rows") or []))
PY
```

예상 결과:

```text
snapshot exists = True
concentration rows = 3390 전후
hub rows = 100
```

### route_builder 연결 확인

```bash
python - <<'PY'
from app.scenario.route_builder import build_route

nodes = [
    {"node_id": "tour_2783547", "name": "독립선언문 배부 터", "map_x": 126.9865255983, "map_y": 37.5752617096, "dist_m": 55.0},
    {"node_id": "tour_128553", "name": "쌈지길", "map_x": 126.9848674428, "map_y": 37.5743062352, "dist_m": 126.8},
    {"node_id": "tour_127454", "name": "서울 운현궁", "map_x": 126.9871421746, "map_y": 37.5764588036, "dist_m": 191.1},
    {"node_id": "tour_3080583", "name": "필소굿캘리", "map_x": 126.9836841991, "map_y": 37.5749561384, "dist_m": 205.9},
    {"node_id": "tour_2666751", "name": "안녕인사동", "map_x": 126.9835620013, "map_y": 37.5744839692, "dist_m": 224.2},
    {"node_id": "tour_250358", "name": "서울 우정총국", "map_x": 126.982, "map_y": 37.575, "dist_m": 297.8},
    {"node_id": "tour_1605933", "name": "탑골공원 팔각정", "map_x": 126.988, "map_y": 37.571, "dist_m": 545.8},
]

route = build_route(nodes, count=7, lowtraffic_k=2, no_meals=True)

for i, n in enumerate(route):
    print(i, n["node_id"], n["name"], n.get("density_tier"), n.get("dist_m"))
PY
```

예상 결과:

```text
low_traffic node가 2개 포함
```

### 시나리오 생성 확인

```bash
python - <<'PY'
import asyncio
from app.scenario.generator import generate_basic_scenario

async def main():
    scn = await generate_basic_scenario(
        126.986,
        37.575,
        region="종로",
        radius_m=2000,
        count=7,
        with_dialogue=False,
        with_content=False,
        no_meals=True,
    )

    for q in scn["node_sequence"]:
        print(q["order"], q["name"], q["density_tier"], q["dist_m"])

asyncio.run(main())
PY
```

---

## 12. 성능 확인 결과

| 항목 | 결과 |
|---|---:|
| BigData cold snapshot | 4.002초 |
| BigData warm snapshot | 0.000079초 |
| concentration rows | 3390 |
| hub rows | 100 |
| select_lowtraffic_anchors 평균 | 0.112초 |
| scenario cold | 7.88초 |
| scenario warm | 0.23~0.98초 |
| 기능 OFF 평균 | 0.954초 |
| ON k=1 평균 | 1.098초 |
| ON k=2 평균 | 1.226초 |
| 동시 5요청 total | 5.743초 |

요약:

```text
cold cache에서는 BigData 벌크 조회 때문에 약 4초가 추가된다.
warm cache 이후에는 snapshot 조회가 거의 0초로 감소한다.
비인기 기능 ON/OFF 차이는 k=1 기준 약 0.14초, k=2 기준 약 0.27초 수준이다.
```

---

## 13. 한계 및 추후 개선

현재 한계:

```text
- generator.py 수정 금지 조건 때문에 BigData helper는 sync 방식
- cache miss 시 첫 요청이 느릴 수 있음
- 모듈 레벨 캐시는 같은 Python 프로세스 안에서만 유지
- MVP는 종로 기준이므로 지역 확장 시 region_code_map 추가 필요
```

추후 개선:

```text
- generator.py에서 BigData snapshot을 async로 선조회
- Redis 캐시로 멀티 워커 환경에서도 snapshot 공유
- 지역별 areaCd/signguCd 매핑 확대
- TarRlteTarService1로 동선 자연스러움 점수 추가
- DataLabService 방문자수 기반 보상 가중치 조정
```