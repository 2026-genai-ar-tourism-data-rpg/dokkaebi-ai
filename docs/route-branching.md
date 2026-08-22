# 경로 분기(route-branching) 설계 — node_sequence 선형 → 트리

> 이슈 #24 · 상위 `.github#5` · 브랜치 `route-branching/kys/v1` · 작성 kys

## 1. 무엇을 바꾸나
지금까지 시나리오의 `node_sequence`는 **한 줄(선형)** 이었다. 여기에 **갈림길(route 분기)** 을
얹어, 플레이어의 선택에 따라 **다음 노드가 갈라지는 트리**로 만든다.
런타임 대화 분기(`branching_service.run_branching`)는 이미 배선돼 있고, 그것은 *한 노드 안*의
대사 선택지다. 이번 작업은 그 위에 얹는 **노드 간(route) 분기**다.

## 2. 핵심 결정 — eager vs lazy

| 축 | **eager (생성 시 트리 확정)** | lazy (밟을 때 생성) |
|---|---|---|
| 생성 시점 | 시나리오 생성 1회에 갈래까지 다 만든다 | 갈림길에서 선택하는 순간 다음 갈래를 생성 |
| 오프라인 플레이 | ✅ 통째로 캐시(앱 `ScenarioStore`가 이미 전체 저장) | ❌ 갈림길마다 온라인 호출 필요 |
| 지연(latency) | 생성 때 한 번(이미 감수 중) | 갈림길에서 스파이크 |
| LLM 비용 | 안 밟는 갈래도 생성(낭비 가능) | 밟는 갈래만 — 절약 |
| 노드 폭발 | 갈래가 깊게 중첩되면 조합폭발 | 밟은 만큼만 |
| 상태/계약 | `node_sequence`+`route_tree` 한 덩어리(무상태) | 부분 시나리오 영속 + 새 엔드포인트 + 진행상태 필요 |

### 결정: **eager, 단 "유계 다이아몬드"** (MVP)
- 갈림길은 **딱 1곳**, 갈래는 **2개(원래 길 / 샛길)**, 그리고 **바로 다음 노드에서 재합류**한다.
  ```
        … → BP ─┬─ (원래 길) M ─┐
                └─ (샛길)   A ─┴─ R → …   (재합류)
  ```
- 이렇게 하면:
  - **노드 수가 선형**으로 유지된다(본선 N + 샛길 1). 조합폭발 없음.
  - **오프라인·결정론적** — 앱은 지금처럼 시나리오 1개만 받아 통째로 캐시·플레이.
  - 갈림길 대사·선택지는 **정적(무LLM)** 이라 추가 비용은 *샛길 노드 콘텐츠 1개*뿐.
- 즉 eager의 단점(폭발·낭비)을 **구조(유계+재합류)** 로 상쇄한다.

### lazy는 언제? (다음 단계)
- 갈림길이 **여러 곳·깊게 중첩**되거나, 갈래가 재합류하지 않고 **끝까지 갈라져** 나갈 때.
- 그때는 이 `route_tree`의 리프에 `"lazy": true` 표식을 두고, 도달 시 `run_branching` seam을
  재사용해 다음 갈래를 생성(부분 시나리오 append). 지금 구조가 그 확장을 막지 않는다.

## 3. 데이터 모양 (계약)
`node_sequence`는 **호환 유지** — 여전히 퀘스트 dict 배열이고, 본선 노드는 그대로다.
분기가 있으면 다음이 **추가**된다.

- 각 노드에 `path_id`: `"main"`(본선) | `"b1"`(샛길).
- 분기 노드(BP)에 `branch`: 앱이 선택지 렌더용.
  ```json
  "branch": {
    "prompt": "갈림길이로다. 어느 길로 가려느냐?",
    "options": [
      {"choice_id": "main", "label": "본래 길 — 「…」 쪽으로", "next_node_id": "<M>"},
      {"choice_id": "b1",   "label": "새어 나온 혼불을 따라 「…」로", "next_node_id": "<A>"}
    ]
  }
  ```
- 응답 최상위에 `is_branching: bool`, `route_tree`:
  ```json
  "route_tree": {
    "entry_node_id": "<첫 노드>",
    "branch_points": ["<BP>"],
    "nodes": { "<id>": {"next": "<id|null>", "choices": [ … BP만 ]} }
  }
  ```
- 샛길 노드(A)는 본선 M의 **대안**이라 기억석 조각 수(`stone_total`)에 넣지 않는다.
  `stone_no=None`, `fragment_id="{region}_branch_b1"`. (조각 회계는 후속 과제)

## 4. 게이팅 / 호환
- 요청 `with_branching: bool = False` (기본 off) → **선형 그대로**(behavior preserving).
  기존 테스트·앱·서버 계약 무변경. `True`일 때만 트리 생성.
- 경로가 짧거나(노드<4) 샛길 예비 후보가 없으면 **자동으로 선형 폴백**(`is_branching=False`).

## 5. 코드 위치
- 순수 로직(선택·픽·조립·검증·순회): `app/scenario/route_branching.py`
- 오케스트레이션(샛길 콘텐츠 생성 + 조립): `generator._apply_branching`
- 테스트: `tests/scenario/test_branching.py` (오프라인·결정론, LLM/네트워크 없음)

## 6. 완료 조건(DoD) 대응
- [x] 분기 route 생성·플레이 1케이스 동작 → `test_branching` (두 갈래 traverse가 각각
      `main`/`b1`을 지나 **공통 재합류 노드**에 도달) + 라이브 생성 E2E.
- [x] eager/lazy 결정 근거 문서 → 본 문서 §2.

---

## 7. [v2] 갈림길은 대화가 묻는다 (2026-08-19 · `dialogue-rework/kys/v1`)

2026-08-18 실측에서 드러난 것: **선택이 두 축으로 갈라져 있었다.** 경로 선택
(`main`/`b1`, 코드가 만든 고정 문구)은 지도 시트에서 고르고, 대화 선택(`c0`/`c1`/`collect`,
LLM 생성)은 플레이 화면에서 골랐다. 도깨비는 갈림길이 있다는 사실 자체를 몰랐고,
앱이 고른 갈래는 서버로 가지 않아 `quest_runs.choices`가 늘 비어 있었다.

### 바뀐 계약
- 앱이 대화 요청에 `branch`(=`node_sequence[BP].branch`)를 실어 보낸다.
  AI는 시나리오를 들고 있지 않으므로(무상태) 이걸 받아야 갈림길을 인지한다.
- 갈림길 노드에서 대화의 **종료 선택지 id = 갈래 id(`main`/`b1`)**.
  앱은 그 값을 그대로 `POST /runs/{runId}/nodes/{nodeId}/complete`의 `choice_id`로 넘긴다.
- 갈림길 노드는 깊이상한(`max_dialogue_turns`)에서 종료하지 않는다 — 잡담만 끝내고
  길 선택만 남긴다. 선택이 없으면 다음 노드를 정할 수 없기 때문.
- 지도 시트는 **폴백**으로만 남는다(대화가 실패해 선택을 못 받은 경우).

### 선택지 사본의 원본
같은 선택지가 두 곳에 있었다(`node.branch.options` / `route_tree.nodes[BP].choices`).
앱은 앞을, 서버 `nextNodeId`는 뒤를 읽어 한쪽만 고치면 조용히 갈라진다.

- **원본 = `node.branch`** — 표시 문구(`label`)는 여기에만 산다.
- `route_tree.nodes[BP].choices`는 **간선 계산용 파생 사본** — `choice_id`·`next_node_id`만.

앱·서버 파서 모두 `label` 부재를 빈 문자열로 읽으므로 하위호환이다.
