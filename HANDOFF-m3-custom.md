# [설계 초안] M3 위시리스트 기반 맞춤 생성 — 앵커 + 샛길

> 작성: 박준형 (pjh) · 2026-07-11 · 상태: **초안 — 팀 합의 전**
> 상위: WEEKLY-PLAN(07-05) §2 pjh "(M3 선행) 위시리스트 기반 맞춤 생성(앵커+샛길) 설계 착수"
> 관련 코드: wishlist.py(jch) · density.py(ljs) · food.py(pjh) · route_builder.py/generator.py(kys — 수정 금지 영역)
> 관련 기획: 11-2 앵커+샛길 · 10 관광 분산

---

## 0. 한 줄 정의

**"사용자가 찜한 곳(위시 앵커)을 중심으로, 그 주변의 비인기 장소(샛길)를 엮어
'취향 + 분산'이 동시에 반영된 코스를 생성한다."**

---

## 1. 현재 상태 vs M3 목표

### 현재 (M2 — 이번 주 통합 완료 상태)

```
build_route ①:
  anchors  = select_wishlist_anchors(nodes, wishlist)     # 위시 → 앵커
  anchors += select_lowtraffic_anchors(nodes, k)          # 비인기 → 앵커
             ↑ 두 hook이 서로를 전혀 모름 (독립 실행)
  route = 앵커 우선 + 거리순 채움 → NN/2-opt 정렬 → 피날레 → 식음 삽입
```

- 비인기 앵커는 **위시와 무관하게** 지역 전체에서 집중률 낮은 순으로 선택된다.
- 즉 지금은 "위시도 넣고 비인기도 넣는" 것이지 "위시에 **맞춘**" 것이 아니다.

### M3 목표

```
위시 "경복궁" → 경복궁 '근처의' 비인기 장소가 샛길로 우선 선택됨
위시 2개면  → 두 위시를 잇는 동선 주변에서 샛길 선택
```

**"맞춤" = 위시가 샛길 선택에 영향을 주는 것.** 이것이 이 설계의 전부다.

---

## 2. 핵심 설계 — 위시-연동 샛길 선택

### 2.1 알고리즘 (제안)

`select_lowtraffic_anchors`에 **위시 앵커를 컨텍스트로 전달**하고,
후보 스코어에 "위시 근접도"를 추가한다.

```
현재 정렬 키:  (avg_rate ↑, hub_rank ↓, dist_m ↑)         # 출발점 기준
제안 정렬 키:  (wish_proximity_score, avg_rate ↑, ...)     # 위시 기준 우선
```

**wish_proximity_score (제안):**
- 각 비인기 후보에 대해 `min(모든 위시 앵커까지의 haversine 거리)`를 계산
- `wish_sidepath_radius_m`(신규 정책값, 제안 800m) 이내면 우선 그룹, 밖이면 후순위 그룹
- 위시가 0개면 → 현재 로직 그대로 (behavior preserving, 기존 hook 계약 유지)

**시그니처 변경 (ljs 협의 필요):**
```python
select_lowtraffic_anchors(nodes, k, wish_anchors: list[dict] | None = None)
# 기본값 None → 기존 호출부 100% 호환
```

**배선 변경 (kys 협의 필요):** route_builder ① 단계에서
```python
wish_anchors = select_wishlist_anchors(nodes, wishlist or [])
anchors = wish_anchors + select_lowtraffic_anchors(nodes, k, wish_anchors=wish_anchors)
```
→ 한 줄 변경. 순서 의존(위시 먼저)이 생기지만 이미 그 순서로 호출 중.

### 2.2 왜 이 방식인가 (대안 비교)

| 방식 | 장점 | 단점 | 판정 |
|---|---|---|---|
| **A. 스코어에 위시 근접도 추가** (제안) | 기존 hook 구조 유지, 변경 최소, 위시 0개면 완전 호환 | 위시-샛길 반경이 정책값 하나 추가됨 | ✅ 채택 제안 |
| B. 위시별로 반경 재검색 (TourAPI 재호출) | 반경 밖 위시도 샛길 확보 가능 | API 호출 증가, 캐시 복잡, 지연 | M3 이후 검토 |
| C. LLM에게 조합 위임 | 유연 | 비결정론 — ① 선택 단계는 결정론 원칙(스냅샷 §0) 위반 | ❌ |

---

## 3. 앵커 우선순위·절삭 규칙 (팀 합의 필요 ⚠️)

현재 `_select_count`는 `anchors → 거리순 채움 → selected[:count]`로,
**앵커끼리의 우선순위 없이 리스트 순서로만** 잘린다. M3에서 앵커 종류가 늘면 규칙이 필요하다.

**제안 우선순위:** `위시 > 비인기 샛길 > 거리순 일반`

| 상황 | 제안 동작 |
|---|---|
| 위시 3 + 샛길 2, count=5 | 전부 포함 (딱 맞음) |
| 위시 4 + 샛길 2, count=5 | 위시 4 + 샛길 1 (샛길부터 절삭) |
| 위시 6, count=5 | ⚠️ 결정 C 미해결 — 아래 §5 |
| 위시 0 | 현재 동작 그대로 (비인기 k개 + 거리순) |

근거: 위시는 사용자의 **명시적** 의사, 샛길은 시스템의 **제안**. 명시가 제안을 이긴다.

---

## 4. 식음(pjh 영역)과의 상호작용

`WishItem.kind`에 `restaurant`가 예약돼 있다("나중" 표기). M3에서 열리면:

| 케이스 | 제안 정책 |
|---|---|
| 위시가 식당 + 예산 밴드 **이내** | 식음 슬롯 1개를 위시 식당으로 **대체** (interleave가 삽입 위치만 결정) |
| 위시가 식당 + 예산 밴드 **초과** | ⚠️ 충돌: "사용자가 찜했는데 예산이 막음". 제안 = **위시 우선 + 앱에 예산 초과 경고 표시** (위시=명시적 의사 원칙과 일관) |
| 위시 식당 + no_meals=True | 모순 입력. 제안 = 위시 우선(식당 포함), 경고 표시 |
| 위시 식당의 price_band 미상 | 위시는 게이팅 대상이 아니므로 포함 (미상 하드컷은 '시스템 추천'에만 적용) |

구현 위치: `interleave_food`에 `wish_food_nodes` 인자 추가 (기본 [] → 기존 호환).
food.py 내부 변경만으로 가능 — **pjh 단독 작업 범위.**

---

## 5. seam 변경 요청 목록 (→ kys)

이 설계는 아래가 선행돼야 완전해진다. 전부 kys 통합 영역(직접 수정 금지)이라 **요청으로 전달**:

1. **결정 B 실현** — `generate_basic_scenario`의 `if not nodes: raise` 완화
   (반경 내 후보 0 + 위시만 → 위시 코스 생성 허용). wishlist.py docstring NOTE 참조.
2. **결정 C 실현** — `_select_count`의 `selected[:count]` 절삭에 §3 우선순위 반영
   (또는 앵커 초과 시 count 확장 허용 — 팀 결정).
3. **배선 1줄** — §2.1의 `wish_anchors` 전달.
4. (선택) `ScenarioRequest`에 `wish_sidepath_radius_m` 노출 여부 — env 정책값으로 충분하면 불필요.

---

## 6. 신규 정책값 (config)

```python
wish_sidepath_radius_m: int = 800        # 위시 주변 샛길 탐색 반경 (제안값 — 종로 도보 10분)
wish_food_over_budget_policy: str = "allow_with_warning"   # §4 둘째 케이스
```

둘 다 env 무코드 튜닝 가능 컨벤션 유지.

---

## 7. 미해결 / 팀 합의 필요 (회의 안건)

- [ ] §2.1 알고리즘 방식 A 채택 여부 (특히 ljs — density.py 시그니처 변경 당사자)
- [ ] §3 절삭 우선순위 "위시 > 샛길" 합의 + 결정 C 처리 방식 (절삭 vs count 확장)
- [ ] §4 예산 초과 위시 식당 정책 (경고 문구는 jch의 "반경 밖 경고 정책"과 묶어서)
- [ ] wish_sidepath_radius_m 기본값 (800m 제안 — 종로 실동선 기준 검증 필요)
- [ ] 비인기 매칭 이슈(snapshot↔TourAPI 이름 매칭, ljs 진행 중)가 선행 — 샛길 자체가 0개면 이 설계 전체가 공회전

## 8. 구현 순서 (M3 진입 시)

```
① ljs 비인기 매칭 픽스 (선행 — 진행 중)
② pjh: density.py 시그니처 + 근접 스코어 (ljs 합의 후, 파일 오너 조율)
③ kys: seam 3건 (§5)
④ pjh: 식음-위시 연동 (§4 — food.py 단독)
⑤ 전 조건 ON E2E 재검증 (위시+샛길+식음+예산)
```

---

*문서 위치 제안: 레포 루트 `HANDOFF-m3-custom.md` 또는 `docs/`. 팀 컨벤션 따름.*
