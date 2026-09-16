# AI 연동 반영 (2026-09-16)

근거: `도깨비-AI연동-협의사항-20260916.pdf`.

## 생성 코스 엔딩

동적 생성 코스의 `node_sequence`에서 `is_finale: true`인 노드에 다음 필드를 붙인다.
종로 고정 대본과 같은 위치·형식을 쓴다.

- `final_restore_dialogue`: 지역과 피날레 장소를 반영한 복원 대사
- `endings.A`, `endings.B`: 각각 굿/노멀 엔딩. `id`, `choice_text`, `ending`, `npc_dialogue`(문자열 배열), `rewards` 포함
- `actions`의 `report` 직전에 `listen` 액션(`slot: "ending_choice"`, A/B 선택지) 추가
- `final_rewards_common.region_stone`: 지역 기억석 이름·설명

두 엔딩 모두 같은 칭호와 지역 기억석을 준다. 엔딩은 플레이어의 A/B 선택으로 정해진다.
친밀도·쿠폰 기준 자동 분기는 협의 문서에 기준이 없으므로 아직 적용하지 않았다.
엔딩 문구는 지역명·마지막 장소명에 맞춘 안전한 템플릿이다. 역사 사실이나 특정 유물은
근거 없이 만들지 않는다. 앱은 고정된 세종대왕·종로 엔딩 대신 이 필드를 사용해야 한다.

## 보상 값

AI가 생성하는 퀴즈의 `correct.exp`를 제거했다. 경험치 지급량은 서버의 조각·피날레
기준을 사용한다. AI 쿠폰 금액은 `app/config.py`의 `scenario_quiz_coupon`,
`scenario_choice_coupon`, `scenario_food_coupon`으로 관리한다. 앱이 실제 지급하는 쿠폰을
서버에 기록할지는 서버 API·저장 모델과 함께 결정해야 한다. 현재 AI 응답만으로 기기 간
쿠폰 동기화는 되지 않는다.

## 기존 설정 확인

- 멀티턴: `/v1/dialogue/turn`은 `done`, `grants`, 갈림길 선택지를 반환한다.
- 갈림길: 생성 요청 `with_branching: true`로 켠다. 앱은 선택 `choice_id`를 서버 run 완료에 전달한다.
- 힌트: 생성 후 `hint_ladder`를 쉬움 3 / 보통 2 / 어려움 1개로 제한한다.
- 도착 반경: 현재 전 난이도 50m. 현장 검증 전 150/100/60m로 변경하지 않았다.
- 식음 노드: `DOKKAEBI_SCENARIO_FOOD_PER_ROUTE` 설정으로 켠다. 기본값은 0이다.
- 검색: `/v1/search`의 기본 `content_type_id`는 관광지 12다.
- 한적한 명소: `density.reward_weight`는 아직 실제 보상 지급에 연결되지 않았다.
