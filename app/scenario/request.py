# ============================================================
# [v1] 시나리오 생성 입력 contract — 사용자 입력 모델
# pipeline: AI 백엔드 / 시나리오 (앱→서버→AI 입력 계약)
# 구현(요약): ScenarioRequest 데이터클래스. 좌표는 앱(GPS/카카오)에서 해석해 넘김 —
#            AI는 좌표를 받을 뿐 카카오 호출 안 함. wishlist는 contentId 확정분(모호함 방지).
# 구현일: 2026-06-18 | 작성: kys (scenario-input/kys/v1)
# ============================================================
from dataclasses import dataclass, field


@dataclass
class LatLng:
    """좌표(위도 lat, 경도 lng). 앱이 GPS/카카오로 해석해 넘김."""
    lat: float
    lng: float


@dataclass
class WishItem:
    """위시리스트 항목 — 자동완성(searchKeyword2)에서 '확정된' 1개. 이름 문자열 ❌(모호)."""
    content_id: str
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
    no_meals: bool = False                         # 선택 — '밥 안 먹음' → 식음 노드 통째 skip
    region: str = "종로"
    # 나중 입력(자리만): visit_date · companions(혼자/친구) · difficulty
    with_dialogue: bool = True                     # NPC 대사 LLM 생성 여부(토큰)
    with_content: bool = True                      # 퀴즈·지령 생성 여부(토큰)
