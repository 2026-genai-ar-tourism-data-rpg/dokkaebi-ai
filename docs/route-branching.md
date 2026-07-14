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
