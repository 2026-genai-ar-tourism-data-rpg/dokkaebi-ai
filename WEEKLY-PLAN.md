# 이번 주차 역할분담 — 시나리오 생성 고도화

> 기준일: 2026-06-23 · 대상: `dokkaebi-ai` 시나리오 파이프라인
> 목표: 기본 시나리오 생성(거리순 v0) → **조건 기반 시나리오 생성**으로 확장

이 문서는 "각자 만드는 게 **파이프라인 어디에 위치하는지**"를 정리한다.
함수 구현 방법이 아니라 **위치·경계·의존순서**가 핵심.

---

## 0. 먼저 알아야 할 파이프라인 구조 (멘탈 모델)

시나리오 생성은 **두 단계로 갈려 있다.** 이게 분담의 전제.

```
[입력: 좌표·반경·위시·예산·이동수단]
   │
   ▼
┌─ ① 선택 단계 (결정론적 · LLM 없음 · 싸다) ──────────────────┐
│   TourAPI 거리순 후보(좌표 수학)                             │
│   → build_route: 반경·위시·비인기·식당·예산·피날레로 거른다    │   ← 조건은 전부 여기 쌓인다
│   → "어떤 장소 N개를, 어떤 순서로"  확정                      │
└────────────────────────────────────────────────────────────┘
   │  (노드 N개 확정)
   ▼
┌─ ② 생성 단계 (LLM · 노드별 병렬) ────────────────────────────┐
│   노드마다: 대사 1콜 + 미션 1콜  (asyncio.gather 병렬)        │   ← 대화 그래프가 노드당 1번 invoke
│   비용은 '조건 수'가 아니라 '노드 수'에만 비례                 │
└────────────────────────────────────────────────────────────┘
   │
   ▼
[③ 조립: _build_quest — 순수 파이썬]
```

**핵심 원칙**
- 노드(장소)는 **LLM이 아니라 TourAPI+좌표**로 정한다. LLM은 "어디 갈지"를 안 정한다.
- 새 기능 조건(반경·비인기·위시·식당·예산)은 **전부 ① 선택 단계**에 붙는다 → LLM 비용 0, 결정론적, 테스트 가능.
- LLM 층(②)은 모양이 안 변한다. **단 하나의 예외 = 경로 분기**(아래 김예슬 항목).

---

## 1. 선행 작업 (완료 ✅) — seam

`route = nodes[:count]` 한 줄을 **hook 가능한 `build_route()`**로 추출 완료.
기본 hook은 전부 no-op이라 **현재 거리순 동작 100% 보존**(검증됨).

| 파일 | 역할 |
|---|---|
| `app/scenario/route_builder.py` | `build_route()` 오케스트레이터 (①선택 단계의 뼈대) |
| `app/scenario/wishlist.py` | 위시 앵커 hook (STUB) |
| `app/scenario/density.py` | 비인기 앵커 hook (STUB 추가) |
| `app/tourapi/food.py` | 식음 삽입 hook (STUB 추가) |
| `request/schemas/routes/config` | `no_meals` 입력 + hook 스위치 미리 배선 |

> 결과: **각자 자기 파일의 STUB 함수만 채우면** generator를 안 건드려도 파이프라인에 연결된다.

---

## 2. 사람별 분담 — "파이프라인 어디에 위치하나"

### 🟦 김예슬 (kys) — ① seam 오너 + 경로 분기(②의 모양 변경)
- **위치:** ① 선택 단계 뼈대(`build_route`) + 유일하게 ②의 모양을 바꾸는 작업
- **이번 주:**
  - [x] seam(`build_route`) 깔고 `dev` 머지 → 나머지 3명 언블락
  - [ ] **경로 분기**: `node_sequence`를 선형 → 트리 구조로. 선택에 따라 다음 노드가 갈림
  - [ ] 분기는 **eager(미리 다 생성) → lazy(밟을 때 생성)** 결정이 핵심. 런타임 `run_branching` 위에 얹기
- **브랜치:** `route-seam/kys/v1`(완료) → `route-branching/kys/v1`
- **경계:** 분기만 ②를 건드림. 나머지 3명은 ① 안에서만 작업 → 충돌 없음

### 🟩 이지선 — ② 아님, **① 비인기 앵커 선택**
- **위치:** ① 선택 단계 — "어떤 장소"에 비인기 샛길을 끼워넣음
- **이번 주:**
  - [ ] `density.py::density_label` mock → **빅데이터 실수치**(집중률 `TatsCnctrRate` + 중심성 `LocgoHubTar` EDA 컷오프)
  - [ ] `density.py::select_lowtraffic_anchors` 구현 (STUB 채우기)
  - [ ] `config.scenario_lowtraffic_anchors` > 0 으로 스위치 ON
- **건드리는 파일:** `density.py`, `bigdata.py`(데이터 접근층, 이미 있음)
- **브랜치:** `lowtraffic-select/ljs/v1`
- **경계:** generator/route_builder 안 건드림 (hook 함수만)

### 🟨 정찬희 — **① 위시 앵커 강제포함 + ④ 반경 엣지**
- **위치:** ① 선택 단계 — 사용자가 "꼭 갈 곳"을 경로에 강제 포함
- **이번 주:**
  - [ ] `wishlist.py::select_wishlist_anchors` 구현 (STUB 채우기) — content_id 매칭 + 반경 밖이면 좌표로 합성 노드
  - [ ] 반경(④) 마무리: 반경 내 후보 0개 폴백, 위시가 반경 밖일 때 경고 정책
- **건드리는 파일:** `wishlist.py`(신규, 본인 것)
- **브랜치:** `wishlist-anchor/jch/v1`
- **경계:** generator/route_builder 안 건드림 (hook 함수만)

### 🟧 박준형 — **① 식음 삽입 + 예산 게이팅**
- **위치:** ① 선택 단계 마지막 — 확정된 동선 사이에 카페/식당 삽입
- **이번 주:**
  - [ ] `food.py::nearby_food` mock → **TourAPI contentTypeId=39**(음식점)/카카오 실데이터
  - [ ] `food.py::interleave_food` 구현 (STUB 채우기) — 동선 중간 삽입 + 예산 내 게이팅
  - [ ] ⚠️ 삽입 식음 노드는 `kind="food"/"cafe"` 마커 → `generator._build_quest`가 **기억석 조각으로 오인 안 하게** 분기 협의 (김예슬과)
  - [ ] `no_meals=True`면 통째 skip은 이미 build_route가 처리 (확인만)
- **건드리는 파일:** `food.py`(본인 것)
- **브랜치:** `food-budget/pjh/v1`
- **경계:** ②(LLM) 안 건드림. 단 `_build_quest` 분기는 김예슬과 한 PR로 조율

---

## 3. 의존 순서 & 충돌 방지

```
김예슬 seam (route-seam/kys/v1)  ──► dev 머지  ──┬─► 박준형  (병렬)
                                                 ├─► 이지선  (병렬)
                                                 └─► 정찬희  (병렬)
김예슬은 머지 후 route-branching 착수 (병렬)
```

**규칙**
1. seam은 `dev` 머지 완료 ✅ → 셋은 지금 바로 병렬 시작 가능
2. 셋은 **각자 hook 파일만** 수정. `generator.py` / `route_builder.py` 직접 수정 금지
3. 입력 필드(`no_meals` 등)는 seam에서 미리 깔아둠 → `request/schemas/routes` 건드릴 일 없음
4. 유일한 cross-talk = **박준형 식음노드 ↔ 김예슬 `_build_quest`**(기억석 오인 방지) → 한 PR로 조율

---

## 4. 한 줄 요약

> **조건이 늘어도 LLM 파이프라인(②)은 안 무거워진다.** 복잡도는 결정론적 선택 단계(① `build_route`)에 모인다.
> 박준형·이지선·정찬희 = ① 안의 각 hook / 김예슬 = ① 뼈대 + ②의 모양을 바꾸는 경로 분기.
