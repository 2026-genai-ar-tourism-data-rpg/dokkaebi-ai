# ============================================================
# [v1] 시나리오 생성 입력 contract — 사용자 입력 모델
# pipeline: AI 백엔드 / 시나리오 (앱→서버→AI 입력 계약)
# 구현(요약): ScenarioRequest 데이터클래스. 좌표는 앱(GPS/카카오)에서 해석해 넘김 —
#            AI는 좌표를 받을 뿐 카카오 호출 안 함. wishlist는 contentId 확정분(모호함 방지).
# 구현일: 2026-06-18 | 작성: kys (scenario-input/kys/v1)
# ------------------------------------------------------------
# [v2] headcount(인원수) 입력 추가 — 식음 예산 게이팅의 1인 예산 산출용.
# 구현(요약): food.py는 budget/headcount로 목표 가격대 밴드를 정하는데 입력 계약에
#            인원수가 없어 항상 1인 기준이었다(4인 총예산 5만원 → 1인 5만원으로 오인).
#            기본값 1 = 미전송 시 기존 동작 그대로(하위호환). 앱 「여행 조건」 화면의
#            인원 입력 추가는 별건(앱 팀 협의) — 서버는 받을 준비만 해둔다.
# 구현일: 2026-08-12 | 작성: pjh (ai-logic-fix/pjh/v2)
# ------------------------------------------------------------
# [v3] 앱 마법사 입력 배선 — duration·companion·difficulty·tags·use_fixed_script 추가.
# 구현(요약): 앱 「나만의 코스 만들기」 3단계에서 받는 시간·동행·난이도·취향이 계약에 없어
#            로컬에만 남고 생성에는 하나도 반영되지 않았다(앱 explore_draft.dart 주석 참조).
#            preference.py가 이 값들을 노드 수·반경·트리거 반경·힌트 수·후보 가중으로 번역한다.
#            use_fixed_script = 종로 정답지 고정 재생을 '명시 요청'했을 때만 켠다 — region만
#            보고 우회하면 사용자가 무엇을 고르든 같은 코스가 나온다(#50 회귀).
#            전부 기본값이 있어 미전송 시 기존 동작 그대로.
# 구현일: 2026-08-18 | 작성: kys (explore-input-wiring/kys/v1)
# ============================================================
from dataclasses import dataclass, field


@dataclass
class LatLng:
    """좌표(위도 lat, 경도 lng). 앱이 GPS/카카오로 해석해 넘김."""
    lat: float
    lng: float


@dataclass
class WishItem:
    """위시리스트 항목 — 자동완성(searchKeyword2)에서 '확정된' 1개. 식별 키는 content_id."""
    content_id: str
    name: str | None = None    # 표시용(합성 앵커 이름). 식별 키 아님 — 매칭은 content_id로
    lat: float | None = None
    lng: float | None = None
    kind: str = "attraction"   # attraction | restaurant(나중)


@dataclass
class ScenarioRequest:
    """시나리오 생성 입력. 필수=user_id·start / 나머지는 선택(없으면 기본·시스템 큐레이션).

    검증·폴백(엣지)은 서버에서: GPS 거부→수동 지정 / 위시 반경 밖→경고 / 빈 입력→큐레이션.
    """
    user_id: str                                   # 필수 — 시나리오 귀속
    start: LatLng                                  # 필수 — 현재 위치(GPS)
    end: LatLng | None = None                      # 선택 — 집(없으면 왕복: 시작=끝)
    radius_m: int | None = None                    # 선택 — 없으면 transport로 자동
    transport: str = "walk"                        # walk | car → 반경 결정
    wishlist: list[WishItem] = field(default_factory=list)  # 선택 — 앵커(여러 개 허용)
    budget: int | None = None                      # 선택 — 식음 예산 게이팅(정찬희) + 표시
    headcount: int = 1                             # 선택 — 인원수. 1인 예산 = budget/headcount
    no_meals: bool = False                         # 선택 — '밥 안 먹음' → 식음 노드 통째 skip
    region: str = "auto"                           # "auto"면 후보 주소에서 시군구 유추
    duration: str = "2h"                           # 2h | half | full → 노드 수·반경 배율
    companion: str = "solo"                        # solo | friend | couple | family → 인원수
    difficulty: str = "normal"                     # easy | normal | hard → 트리거 반경·힌트 수
    tags: list[str] = field(default_factory=list)  # 취향 태그(#고궁·#카페…) → 후보 선호 가중
    use_fixed_script: bool = False                 # 종로 정답지 고정 재생(시연용). 기본=동적 생성
    # 나중 입력(자리만): visit_date
    with_dialogue: bool = True                     # NPC 대사 LLM 생성 여부(토큰)
    with_content: bool = True                      # 퀴즈·지령 생성 여부(토큰)
    with_branching: bool = False                   # 선택 — 갈림길(route 분기) 트리 생성(#24)
