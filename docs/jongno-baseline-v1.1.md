# 종로 정답지 v1.1 — 「종로, 잊혀진 글씨의 비밀」 (4노드 스키마 재기술)

> 작성: 이지선(ljs) · 이슈 #31 · 브랜치 `content-qa-design/ljs/v1`
> 원본 대사·퀴즈·보상: `시나리오_MVP_예시.md`(kys, 2026-06-19, `.github`저장소 report/) — **정답지 지위 그대로 유지**.
> 구조 필드(motivation/strategy/actions/hint_ladder/grants·requires StateRef)는 이 문서에서 신규 부여.
> 스키마 근거: `시나리오_구조화.md` 2절(동기→전략→액션) · 5절(힌트 사다리) · `단서_설계_규칙.md`.
> 실제 앱 계약(`app/scenario/node_schema.py` `validate_app_contract`)과 필드명·StateRef 포맷 정합 확인.

## 0. 시나리오 메타
| 항목 | 값 |
|---|---|
| 지역 | 종로 (`region="종로"`) |
| 노드 | 운현궁 → 익선동 한옥카페 → 인사동 → 🏁 광화문(세종, 피날레) (+ 사이드: 이순신, §5) |
| fragment 총량 | 3 (`stone_total=3`, 운현궁·익선동·인사동에서 1개씩 grants — 광화문은 combine 전용, 신규 조각 없음) |
| 종료조건 | 조각 1·2·3 + 완료 플래그 → 광화문에서 구조적 종료(대화 소진 아님) |
| 예산 | 20,000원 (지출 흐름은 §4) |

> **구현 참고**: 현재 `generator.py`의 stone_no/stone_total 계산은 관광 노드 전부를 균등하게 조각으로 센다.
> 이 시나리오는 광화문(4번째 관광 노드)을 "새 조각이 아닌 복원 병목"으로 설계했으므로, 그대로 생성하면
> `stone_total=4`가 나와 이 문서의 3과 어긋난다. QA 시 이 차이를 감안해서 비교할 것(코드 수정은 이번
> 범위 아님, 발견 사항으로만 기록).

---

## 1. 운현궁 (`node_id: tour_unhyeongung`)

**NPC**: 먹 도깨비 (모티프: 붓·먹 / 말투: ~니라, 허허)
**동기**: M1(기억의 수호) + M7(재주 시험) · **전략**: S4_PHOTO_TRAIL + S3_RIDDLE_UNLOCK

**등장 대사**
> "허허, 운현궁에 발을 들였구나. 흥선대원군이 살던 이 사저에… 어느 날 세종 임금의 글씨 한 조각이 먹물 속으로 숨어버렸느니라. 자네, 글을 아끼는 자인가?"

**선택지**
| id | 텍스트 | 효과 |
|---|---|---|
| A | "세종대왕의 글씨라니, 무슨 일이오?" | flags:["호기심"], affinity:+1 |
| B | "보상은 무엇이오?" | reward_mod:{coupon:+100} |
| C | "그냥 빨리 찾겠소." | (변화 없음) |

**퀴즈**: "운현궁은 누구의 집이었더냐?" 1)세종대왕 2)**흥선대원군**✅ 3)정조 → 정답 exp+30/coupon+200, 오답은 힌트로 재시도(데드락 없음)

**actions**
```json
[
  {"a": "goto", "place": "운현궁"},
  {"a": "listen", "slot": "intro+choices", "choices": [
    {"id": "A", "flags": ["호기심"], "affinity": 1},
    {"id": "B", "reward_mod": {"coupon": 100}},
    {"id": "C"}
  ]},
  {"a": "answer", "quiz": {"answer_idx": 1, "correct": {"exp": 30, "coupon": 200}, "hints": "ladder"}},
  {"a": "capture", "targets": ["대문", "마당", "전통건물 외관"]},
  {"a": "follow", "object": "먹물 발자국", "steps": 3},
  {"a": "tap", "target": "글씨파편", "count": [0, 1]},
  {"a": "report", "npc": "먹 도깨비"}
]
```

**hint_ladder** (H1→H3, 정답 문자열 미노출 확인 완료)
```json
{
  "H1": "발자국은 해 지는 쪽으로 번졌느니",
  "H2": "이로당 처마 아래니라",
  "H3": "처마 그늘 왼편, 세 번째 서까래",
  "open_rule": ["fail1|idle60", "idle90", "button"]
}
```

**grants / requires / reward**
```json
{
  "requires": [], "requires_mode": "none",
  "grants": ["fragment:종로_stone_1of3", "clue:申時"],
  "reward": {"exp": 50, "coupon": {"to": "익선동카페", "amount": 500}},
  "success": ["place_verified", "quiz_correct", "photo_done", "follow:먹물 발자국>=3", "tap:글씨파편>=1"]
}
```

---

## 2. 익선동 한옥카페 (`node_id: tour_ikseondong`)

**NPC**: 한옥 도깨비 (모티프: 기와·차)
**동기**: M6(살림 불림) + M4(평온 회복) · **전략**: S7_PATRONIZE + S3_RIDDLE_UNLOCK
**식음 조건**: 메뉴 주문 인증(영수증/위치), 예상 지출 5,000원 − 쿠폰 500원 = 4,500원
**`kind: "spot"`** (⚠️ `"food"`/`"cafe"`가 아님) — S7 전략 + 조각 grants를 같이 쓰려면 필수.
`kind`가 food/cafe면 `validate_app_contract`가 조각 grants를 막는다(QA 리포트 §2 발견1 참고,
`interleave_food()`로 자동 삽입되는 별도 식음 경유 노드와는 다른 경로 — 이 노드는 본선 anchor).

**등장 대사** (연계 인지 — 申時 단서 소지)
> "허허, 운현궁에서 申時 단서를 얻어 왔구나! 그 시각, 이 골목 가마솥에 글씨 하나가 떨어졌지. 차 한 잔 시키고 천천히 둘러보거라."

**선택지**
| id | 텍스트 | 효과 |
|---|---|---|
| A | "이 골목은 왜 한옥이 많소?" | flags:["한옥통"], affinity:+1 |
| B | "추천 메뉴가 있소?" | (변화 없음) |

**퀴즈**: "익선동의 '익'은 무엇을 뜻하겠느냐?" 1)날개 2)**더할 익(益)**✅ 3)물 → 정답 coupon+300

**actions**
```json
[
  {"a": "goto", "place": "익선동 한옥카페"},
  {"a": "listen", "slot": "intro+choices", "choices": [
    {"id": "A", "flags": ["한옥통"], "affinity": 1},
    {"id": "B"}
  ]},
  {"a": "purchase", "menu": "익선동 한 상", "optional": true, "verification": "receipt"},
  {"a": "answer", "quiz": {"answer_idx": 1, "correct": {"exp": 20, "coupon": 300}, "hints": "ladder"}},
  {"a": "tap", "target": "글씨파편", "count": [0, 1]},
  {"a": "report", "npc": "한옥 도깨비"}
]
```

**hint_ladder** — 퀴즈("익"의 뜻)를 향해 단계적으로 좁힘. 이전에 전달한 초안(찻잔 김 속 탐색)은 이 노드
실제 메커니즘(주문 인증 + 어휘 퀴즈, 물리 탐색 없음)과 안 맞아 아래로 교체함.
```json
{
  "H1": "이 골목 이름에 뜻이 숨어 있느니",
  "H2": "'더한다'는 뜻의 한자를 떠올려 보거라",
  "H3": "날개도 물도 아니다, 무언가를 보태는 글자니라",
  "open_rule": ["fail1|idle60", "idle90", "button"]
}
```

**grants / requires / reward**
```json
{
  "requires": ["clue:申時"], "requires_mode": "soft",
  "grants": ["fragment:종로_stone_2of3", "clue:ㄱ"],
  "reward": {"exp": 40, "coupon": {"to": "인사동", "amount": 1000}},
  "success": ["place_verified", "one_of:purchase_verified|tap_done", "quiz_correct", "tap:글씨파편>=1"]
}
```

---

## 3. 인사동 (`node_id: tour_insadong`)

**NPC**: 붓장수 도깨비
**동기**: M8(물건 되찾기) + M7(재주 시험) · **전략**: S5_PHOTO_PROOF + S3_RIDDLE_UNLOCK

**등장 대사** (연계 인지 — ㄱ 단서 소지)
> "글씨엔 자음과 모음이 있느니. 자네 'ㄱ'은 얻었으나 'ㅏ'가 없구나. 저 전통 간판을 화면에 담아 보거라 — 옛 글씨가 깨어날지니."

**선택지** — 원본 `시나리오_MVP_예시.md`엔 이 노드에 분기 표가 없었음(노드1·2만 있었음). `listen`
액션이 앱 계약상 `choices` 배열을 필수로 요구해서(`validate_app_contract`) 신규 작성.
| id | 텍스트 | 효과 |
|---|---|---|
| A | "이 간판들은 다 무슨 뜻이오?" | flags:["호기심"], affinity:+1 |
| B | "빨리 찾아보겠소." | (변화 없음) |

**사진 미션**: 전통 간판/먹글씨 촬영 인증 → 모음 'ㅏ' 단서 획득
**퀴즈**: "'ㄱ'과 'ㅏ'를 합치면?" 입력 **가**✅ → 상자 개봉·조각 획득. 오답 시 "자음 아래 모음을 붙여 보거라" 힌트.

**actions**
```json
[
  {"a": "goto", "place": "인사동"},
  {"a": "listen", "slot": "intro+choices", "choices": [
    {"id": "A", "text": "이 간판들은 다 무슨 뜻이오?", "flags": ["호기심"], "affinity": 1},
    {"id": "B", "text": "빨리 찾아보겠소."}
  ]},
  {"a": "capture", "targets": ["전통 간판", "먹글씨"]},
  {"a": "answer", "quiz": {"answer_idx": 0, "correct": {"exp": 30, "coupon": 200}, "hints": "ladder",
    "wrong_hint": "자음 아래 모음을 붙여 보거라"}},
  {"a": "tap", "target": "글씨파편", "count": [0, 1]},
  {"a": "report", "npc": "붓장수 도깨비"}
]
```

**hint_ladder** — 이전 초안(먹방울 3개 수집)은 이 노드에 없는 메커니즘(S6_ACCUMULATE)이라 실제 메커니즘
(간판 촬영 → 자음+모음 조합 퀴즈)에 맞춰 아래로 교체함.
```json
{
  "H1": "간판 위 글씨를 눈여겨보거라",
  "H2": "'ㄱ'에 이을 소리가 저 현판 어딘가에 있느니라",
  "H3": "제일 큰 간판을 화면 안에 크게 담아 보거라",
  "open_rule": ["fail1|idle60", "idle90", "button"]
}
```

**grants / requires / reward**
```json
{
  "requires": ["clue:ㄱ"], "requires_mode": "soft",
  "grants": ["fragment:종로_stone_3of3", "clue:ㅏ"],
  "reward": {"exp": 50},
  "success": ["place_verified", "photo_done", "quiz_correct", "tap:글씨파편>=1"]
}
```

---

## 4. 🏁 광화문 광장 · 세종대왕 (피날레, `node_id: tour_gwanghwamun`, `is_finale: true`)

**NPC**: 세종대왕 (역사 인물, 수호급, 위엄+자애)
**동기**: M3(이름 회복) · **전략**: S6_ACCUMULATE(조합) — 액션 원자는 combine 1개, 물리 탐색 없음

**등장 대사**
> "그대가 흩어진 글씨를 모아 왔는가. 백성이 쉬이 익히라 만든 글이거늘, 잊혀선 아니 되네. 마지막 조각은… 그대 마음에 있네."

**최종 선택 → 엔딩 분기**
| 선택 | 엔딩 |
|---|---|
| "백성을 위한 글이었군요." | 굿 엔딩 — 친밀도 만렙, 희귀 유물 "집현전 붓" |
| "보상부터 주시죠." | 노멀 엔딩 — 유물 없음 |

**actions**
```json
[
  {"a": "goto", "place": "광화문광장"},
  {"a": "listen", "slot": "intro+ending_choice", "choices": [
    {"id": "A", "affinity": 3, "reward_mod": {"relic": "집현전 붓"}},
    {"id": "B"}
  ]},
  {"a": "combine", "items": ["fragment:종로_stone_1of3", "fragment:종로_stone_2of3", "fragment:종로_stone_3of3"]},
  {"a": "report", "npc": "세종대왕"}
]
```

**hint_ladder** — 이 노드는 탐색형 퍼즐이 아니라 대화 선택형 종료라, H1~H3은 "무엇을 해야 하는지"
안내 성격으로 작성(정답 유출 대상인 퀴즈 자체가 없음).
```json
{
  "H1": "이제껏 모은 조각을 도깨비에게 보이거라",
  "H2": "세종대왕이 묻거든 마음에 있는 답을 하거라",
  "H3": "정답은 없다 — 어느 쪽을 골라도 조각은 하나로 모이느니라",
  "open_rule": ["fail1|idle60", "idle90", "button"]
}
```

**grants / requires / reward**
```json
{
  "requires": ["fragment:종로_stone_1of3", "fragment:종로_stone_2of3", "fragment:종로_stone_3of3"],
  "requires_mode": "hard",
  "grants": ["flag:종로_복원완료"],
  "reward": {"exp": 200, "title": "종로의 글지기"},
  "success": ["place_verified", "combine_done"]
}
```

---

## 5. 사이드 퀘스트 — 광화문 이순신 장군 (Floating Module, `node_id: side_yisunsin`)

`시나리오_구조화.md` 6절 표의 "사이드" 행 + `시나리오_MVP_예시.md` §3 상세를 그대로 재기술.
1-4절 본선 노드(Episodic Cluster)와 달리 이 노드는 **Floating Module**(`시나리오_구조화.md`
1-1절) — 광화문 도착 시 본선과 별개로 트리거되고, 안 밟아도 본선 진행에 영향 없음(D3 규칙).

**NPC**: 이순신 장군 (역사 인물, 말투: 과묵·결연 — 도깨비체 아님)
**동기**: M3(이름 회복) + M9(위로·전언) · **전략**: S5_PHOTO_PROOF + S3_RIDDLE_UNLOCK
**트리거**: 광화문 도착(메인 피날레와 별개 등장)

**등장 대사**
> "예까지 왔는가. 저 배의 위용을 담아보게. 그 뒤에 내 진법의 뜻을 묻겠네."

**선택지** — 인사동과 같은 이유로 신규 작성(원본엔 사이드 퀘스트 분기 표 없음).
| id | 텍스트 | 효과 |
|---|---|---|
| A | "장군의 활약이 궁금하오." | flags:["호기심"], affinity:+1 |
| B | "바로 살펴보겠소." | (변화 없음) |

**사진 미션**: 거북선 동상 촬영 인증
**퀴즈**: "학익진은 무슨 모양인가?" 1)일자진형 2)**학이 날개 편 모양**✅ 3)원형진

**actions**
```json
[
  {"a": "goto", "place": "광화문광장"},
  {"a": "listen", "slot": "intro+choices", "choices": [
    {"id": "A", "flags": ["호기심"], "affinity": 1},
    {"id": "B"}
  ]},
  {"a": "capture", "targets": ["거북선 동상"]},
  {"a": "answer", "quiz": {"answer_idx": 1, "correct": {"exp": 20}, "hints": "ladder"}},
  {"a": "report", "npc": "이순신 장군"}
]
```

**hint_ladder** (`run_qa`로 정답유출 확인 완료 — 이번엔 오탐 없음)
```json
{
  "H1": "새가 날아오르는 모습을 떠올려 보거라",
  "H2": "이순신 장군이 짠 진법은 새의 날개를 닮았다 하지",
  "H3": "양쪽으로 넓게 펼친 날개, 그 모양이 진법이었느니라",
  "open_rule": ["fail1|idle60", "idle90", "button"]
}
```

**grants / requires / reward**
```json
{
  "requires": [], "requires_mode": "none",
  "grants": ["relic:충무공의 나침반"],
  "reward": {"exp": 20},
  "success": ["place_verified", "photo_done", "quiz_correct"]
}
```
> `relic`은 전역 유물(`시나리오_구조화.md` 3절 상태 어휘) — 다음 지역까지 지속, 본선 조각 총량(3)에는
> 안 잡힘. `run_qa` 실행 결과 `tone_ok=false`(도깨비체 마커 없음)로 뜨는데, 이는 §3-3(광화문
> 세종대왕)과 같은 이유 — 역사 인물 NPC는 의도적으로 다른 말투라 오탐(QA 리포트에 반영 예정).

---

## 6. 예산·쿠폰 흐름 (원본 그대로)
```
운현궁(무료) ── 완료 → 카페 500원 쿠폰
익선동 카페  5,000 − 500 = 4,500원 지출 ── 완료 → 인사동 1,000원 쿠폰
인사동       8,000 − 1,000 = 7,000원 지출
─────────────────────────────────────
총 지출 11,500원 ≤ 예산 20,000원 (여유 8,500원)
```

## 7. 이번 문서에서 바뀐 것 (변경 이력)
- 동기(M1~M9)·전략(S1~S7)·액션 원자·StateRef(grants/requires) 필드 신규 부여 — `시나리오_MVP_예시.md`
  원본엔 없던 구조 필드
- **익선동·인사동 H1~H3 힌트 문구 교정**: 이전에 kys에게 구두 전달했던 초안(찻잔 김 탐색·먹방울 수집)이
  두 노드의 실제 메커니즘과 안 맞아 이 문서 기준으로 대체함. **kys에게 갱신본 재전달 필요.**
- 피날레 fragment 수 불일치(원본 문서 "4조각 합체" 표현 vs 실제 grants 3개) 발견 — 원본 표현은 보존하되
  구조 필드는 실제 grants 개수(3)로 통일. `generator.py`의 stone_total 계산과 차이 나는 점은 §0 참고 기록.
- **사이드 퀘스트(이순신) 추가**(2026-07-31): 이슈 #31 본문 "노드1~4·**사이드**" 요구사항 재확인 후
  누락분 보강 — §5. `시나리오_구조화.md` 6절 표 + `시나리오_MVP_예시.md` §3 기준.
