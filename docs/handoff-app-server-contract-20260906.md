# [핸드오프] 앱·서버 계약 수정 요청 — 결함보고 20260904 #3 · #5

> 작성: pjh · 2026-09-06 · 브랜치 `agent-qa/pjh/v1`
> 근거: `dokkaebi-ai-결함보고-20260904.pdf` (Upstage solar-pro 실키 + TourAPI 실키 점검)
> 대상 레포: **dokkaebi-app**(Flutter) · **dokkaebi-server**(NestJS)
> AI 레포(`dokkaebi-ai`)는 수정할 것이 **없다** — 아래 필드를 모두 이미 받고 있다.

---

## 0. 왜 이 문서가 필요한가

결함 5건 중 #1·#2는 AI 레포 단독으로 고쳤다(커밋 `671a11b`, `6dc252c`).
#4는 `.env` 설정 한 줄이라 이번 범위 밖.
**#3·#5는 앱이 보내지 않는 필드**라서 AI 쪽에서 손댈 수가 없다.

> ⚠️ **서버 `ValidationPipe`가 `whitelist: true`다.** 앱이 필드를 실어 보내도
> 서버 DTO에 그 필드가 없으면 **조용히 잘려 나간다**(에러도 안 난다).
> 그래서 앱·서버를 **같은 PR에서 함께** 고쳐야 한다. 한쪽만 고치면 증상이 그대로다.

---

## 1. 결함 #3 — 마법사에서 고른 조건 4개가 서버로 가지 않는다 (심각도: 높음)

### 증상

입력확인 화면은 시간·동행·난이도·취향을 표로 보여 주지만, 생성 요청에는
`transport`·`wishlist`·`budget`·`no_meals`만 담긴다. 사용자가
"반나절 / 가족 / 어려움 / 역사"를 골라도 **결과가 동일하다.**

### 원인

앱 `explore_draft.dart`에 "서버 미지원 필드라 로컬에만 보관"이라고 적혀 있다.
그런데 AI는 2026-08-18에 이 필드들을 모두 받도록 열어 뒀다. **앱 쪽 정보가 낡았다.**

### 고칠 것

#### (1) 앱 — `POST /scenarios` 요청 본문에 5개 필드 추가

`explore_draft.dart`의 "로컬에만 보관" 주석을 지우고 요청에 싣는다.

#### (2) 서버 — 같은 필드를 DTO에 추가하고 AI로 그대로 전달

`whitelist: true` 때문에 DTO에 없으면 잘린다. 통과만 시키면 된다(가공 불필요).

### 계약 (AI가 이미 받는 형태 — `app/api/schemas.py:ScenarioGenRequest`)

| 필드 | 타입 | 기본값 | 허용값 | AI에서 쓰이는 곳 |
|---|---|---|---|---|
| `duration` | string | `"2h"` | `2h` \| `half` \| `full` | 노드 수(4/6/8) · 검색 반경 배율(×1.0/1.5/2.0) |
| `companion` | string | `"solo"` | `solo` \| `friend` \| `couple` \| `family` | 인원수(1/2/2/4) → 식음 예산 게이팅 |
| `difficulty` | string | `"normal"` | `easy` \| `normal` \| `hard` | GPS 트리거 반경(150/100/60m) · 힌트 수(3/2/1) |
| `tags` | string[] | `[]` | 아래 목록 | 후보 선호 가중(제외 아님 — 태그 1개당 가상거리 −1500m) |
| `use_fixed_script` | bool | `false` | — | 종로 정답지 고정 재생(시연용). **앱은 명시 요청일 때만 true** |

`tags` 허용 문자열 (`app/scenario/preference.py:_TAG_KEYWORDS`):
`고궁` · `역사` · `한옥` · `전통문화` · `카페` · `맛집` · `한적한 곳` · `사진 명소`

> 모르는 값이 와도 AI는 기본값으로 떨어질 뿐 500을 내지 않는다. 다만 오타가 나면
> 조용히 무시되므로 앱 쪽에서 위 문자열을 상수로 고정해 두는 편이 안전하다.

### 연쇄 — `headcount`도 같이 누락된다

AI에 `companion → 인원수` 변환이 있는데 입력이 안 오니 **예산 게이팅이 항상 1인
기준으로 계산된다.** `budget`은 "일행 전체 예상 지출 상한"이고 1인 예산은
`budget / headcount`다.

- 앱이 인원수를 직접 아는 화면이면 `headcount`(정수, ≥1)를 같이 보낸다.
- 안 보내면 AI가 `companion`으로 유추한다(`headcount_for`: 앱이 보낸 값이 1보다 크면 그걸 존중).
- 서버 DTO에도 `headcount`를 추가해야 한다(역시 whitelist 때문).

### 검증 방법

응답 `ScenarioGenResponse`가 요청값을 되돌려 준다 — 잘렸는지 여기서 바로 보인다.

```
duration · companion · difficulty · tags · headcount · transport · budget
```

`"half"`를 보냈는데 응답이 `"2h"`면 **서버 어딘가에서 잘린 것**이다.
`node_sequence` 길이도 4 → 6으로 바뀌어야 한다.

---

## 2. 결함 #5 — 대화 API 호출에 갈림길·노드종류 정보가 빠져 있다 (심각도: 중간)

### 증상

지금은 잠복 상태다 — **기능을 켜는 순간 발현한다.**

앱의 `dialogueTurn`이 `branch` · `kind` · `region_id` · `player_state`를 보내지 않는다.

### 영향

- **`branch`** — AI는 시나리오를 들고 있지 않은 **무상태 서비스**다. 앱이 갈림길
  정보를 실어 줘야 분기를 인지한다. 지금은 `with_branching`이 꺼져 있어 안 터지지만,
  **켜는 순간 갈림길 대화가 깨진다.**
- **`kind`** — 식당·카페 노드에서도 "기억석 조각을 찾아라" 대사가 나간다.
  **결함 #4(식음 노드 0개)를 해결하면 바로 발현된다.**
  → 그래서 `.env`에 `DOKKAEBI_SCENARIO_FOOD_PER_ROUTE`를 켜기 **전에** 이걸 먼저 고쳐야 한다.
- **`region_id`** — grounding 재조회 시 지역 워킹셋 편입에 쓰인다. 없으면 원문 재조회가 약해진다.
- **`player_state`** — `{progress, required}` 진행도. 대사 톤 조절에 쓰인다.

### 계약 (`app/api/schemas.py:DialogueTurnRequest`)

```jsonc
POST /v1/dialogue/turn
{
  "node_id": "tour_123",
  "node_name": "보신각터",
  "region_id": "종로",                 // ← 추가
  "history": [{"role": "npc", "text": "..."}],   // role = npc | me
  "inventory": {"items": ["clue:四結"]},
  "last_choice": "b1",
  "turn": 2,
  "fragment_id": "종로_stone_3of4",
  "kind": "spot",                      // ← 추가. spot | food | cafe
  "player_state": {"progress": 2, "required": 4},   // ← 추가
  "branch": {                          // ← 추가. 갈림길 노드일 때만, 없으면 null
    "prompt": "어느 길로 가겠느냐?",
    "options": [
      {"choice_id": "main", "label": "큰길", "next_node_id": "tour_124"},
      {"choice_id": "b1",   "label": "샛길", "next_node_id": "tour_130"}
    ]
  }
}
```

**`branch`는 앱이 시나리오 payload에서 그대로 꺼내 실어 보내면 된다** —
`node_sequence[i].branch`가 위 구조 그대로다. 가공하지 말 것.

`kind`도 `node_sequence[i].kind`를 그대로 넘긴다.

`choice_id`는 곧 route 갈래 id이고, 앱은 이 값을 서버
`POST /runs/{runId}/nodes/{nodeId}/complete`의 `choice_id`로 넘긴다 — 이미 쓰던 값이다.

### 검증 방법

1. 식음 노드(`kind: "food"`)에서 대화를 걸어 "기억석 조각" 대사가 **안 나오면** 통과.
2. `with_branching: true`로 시나리오를 만들고 갈림길 노드에서 대화 → 선택지가
   `branch.options`의 `label`과 일치하면 통과.

---

## 3. 그 외 — 확인만 필요한 것

### 검색 응답 형태 (서버 레포)

앱은 최상위 배열을 파싱하는데 AI는 `{"candidates": [...]}`로 준다
(`app/api/schemas.py:SearchResponse`, `GET /v1/search`).
**서버가 벗겨 주는지 확인이 필요하다.** 안 벗기면 앱 자동완성이 빈 목록으로 보인다.

```jsonc
// AI가 주는 것
{"candidates": [{"content_id": "126508", "name": "경복궁", "addr": "...", "lat": 37.57, "lng": 126.97}]}
```

### 앱이 `qa_flags`를 파싱하지 않음

`ScenarioGenResponse.qa_flags`(생성 품질 경고)가 앱까지 오지 않는다.
**서버에서만 쓸 값이면 현행 유지로 괜찮다.** 운영 대시보드에 띄울 생각이면 그때 파싱하면 된다.

---

## 4. 정리 — 체크리스트

- [ ] 앱: `POST /scenarios`에 `duration`·`companion`·`difficulty`·`tags`·`headcount`(·`use_fixed_script`) 추가
- [ ] 앱: `explore_draft.dart`의 "서버 미지원 필드" 주석 삭제
- [ ] 서버: 같은 필드를 생성 DTO에 추가(`whitelist: true` 때문에 필수) → AI로 그대로 전달
- [ ] 서버: 응답의 `duration`·`companion`·`difficulty`·`tags`·`headcount` 반환 확인
- [ ] 앱: `dialogueTurn`에 `branch`·`kind`·`region_id`·`player_state` 추가
- [ ] 서버: `/v1/search`의 `{"candidates": [...]}` 언랩 여부 확인
- [ ] **순서 주의**: `.env`의 식음 노드(`DOKKAEBI_SCENARIO_FOOD_PER_ROUTE`)를 켜기 전에
      `kind` 전송을 먼저 배선해야 식음 노드에서 엉뚱한 대사가 안 나온다
