# ============================================================
# [v1] API 스키마 — 대화/시나리오 요청·응답 (Pydantic)
# pipeline: AI 백엔드 / 서빙 레이어 (계약)
# 구현(요약): Dialogue + Scenario 생성 요청/응답 정의
# 구현일: 2026-06-10 (시나리오 추가: 2026-06-18) | 작성: kys
# ============================================================
from pydantic import BaseModel, Field


class DialogueRequest(BaseModel):
    """NPC 대화 요청 — 게임 서버(dokkaebi-server)가 내부 HTTP로 호출."""

    node_id: str = Field(..., description="장소 노드 ID")
    stage: str = Field("등장", description="등장|의뢰|힌트|완료")
    player_state: dict = Field(default_factory=dict, description="진행도·보유 조각·이전 대화 요약")


class DialogueResponse(BaseModel):
    """NPC 대화 응답."""

    response: str
    cache_hit: bool = False


# --- 분기 대화 (찐 RPG, 기획 8-D·7-C) ---
class DialogueTurnRequest(BaseModel):
    """분기 대화 한 턴 — 선택마다 호출(멀티턴). 인벤토리로 연계(7-C)."""
    node_id: str
    node_name: str = ""
    region_id: str = ""
    history: list[dict] = Field(default_factory=list)   # [{role, text}]
    inventory: dict = Field(default_factory=dict)        # {items:[...]} 누적 단서·조각
    last_choice: str | None = None                       # 직전 선택 id('collect'면 종료)
    turn: int = 0                                        # 대화 깊이(상한 초과 시 수렴)
    fragment_id: str | None = None                       # 이 노드 조각 id(획득 시 grants)


class Choice(BaseModel):
    id: str
    text: str


class DialogueTurnResponse(BaseModel):
    """분기 대화 응답 — 대사 + 선택지 + 획득물 + 종료여부."""
    response: str
    choices: list[Choice] = Field(default_factory=list)
    grants: list[str] = Field(default_factory=list)      # 획득한 조각/단서 id
    done: bool = False                                   # 이 노드 대화 완료(조각 획득)


# --- 시나리오 생성 (입력 contract = 아키텍처 5-6) ---
class LatLngSchema(BaseModel):
    """좌표(앱이 GPS/카카오로 해석해 넘김)."""
    lat: float
    lng: float


class WishItemSchema(BaseModel):
    """위시리스트 항목 — searchKeyword2 자동완성에서 확정된 content_id."""
    content_id: str
    lat: float | None = None
    lng: float | None = None
    kind: str = "attraction"


class ScenarioGenRequest(BaseModel):
    """시나리오 생성 요청 — 게임 서버가 내부 HTTP로 호출(앱 입력 전달)."""
    user_id: str
    start: LatLngSchema
    end: LatLngSchema | None = None
    radius_m: int | None = None
    transport: str = "walk"
    wishlist: list[WishItemSchema] = Field(default_factory=list)
    budget: int | None = None
    region: str = "종로"
    with_dialogue: bool = True
    with_content: bool = True


class ScenarioGenResponse(BaseModel):
    """시나리오 생성 응답(노드 시퀀스 + 메타). node_sequence는 퀘스트 dict 배열."""
    scenario_id: str
    title: str
    region: str
    type: str = "custom"
    node_sequence: list[dict]
    anchor_node_id: str | None = None
    is_public: bool = False
    created_by: str | None = None
    budget: int | None = None


# --- 관광지 검색 (앵커 자동완성) ---
class SearchCandidate(BaseModel):
    """검색 후보 1개 — 앱 자동완성 드롭다운 항목."""
    content_id: str
    name: str | None = None
    addr: str | None = None
    lat: float | None = None
    lng: float | None = None


class SearchResponse(BaseModel):
    """관광지 이름 검색 결과(정확 일치 우선 정렬)."""
    candidates: list[SearchCandidate]
