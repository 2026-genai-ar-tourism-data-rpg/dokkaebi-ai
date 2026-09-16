# ============================================================
# [v1] API 스키마 — 대화/시나리오 요청·응답 (Pydantic)
# pipeline: AI 백엔드 / 서빙 레이어 (계약)
# 구현(요약): Dialogue + Scenario 생성 요청/응답 정의
# 구현일: 2026-06-10 (시나리오 추가: 2026-06-18) | 작성: kys
# ------------------------------------------------------------
# [v2] headcount(인원수) 요청/응답 필드 추가 — 식음 예산 게이팅 1인 예산 산출용.
#      기본 1 · ge=1 검증. 미전송 시 기존 동작 그대로(하위호환).
# 구현일: 2026-08-12 | 작성: pjh (ai-logic-fix/pjh/v2)
# ------------------------------------------------------------
# [v3] 앱 마법사 입력 배선 — duration·companion·difficulty·tags·use_fixed_script 요청 필드 +
#      응답 에코(저장·검증용). 서버 DTO(GenerateScenarioDto)와 1:1로 유지할 것 —
#      서버 ValidationPipe가 whitelist:true라 여기 있어도 서버에 없으면 조용히 잘린다.
# 구현일: 2026-08-18 | 작성: kys (explore-input-wiring/kys/v1)
# ------------------------------------------------------------
# [v4] 시나리오 응답에 qa_flags 추가 — 생성 QA 루프(A1)가 못 고친 결함과 미션 제네릭
#      폴백을 사람이 읽는 문장으로 내보낸다. default_factory=list라 기존 호출자 무영향.
# 구현일: 2026-09-04 | 작성: pjh (agent-qa/pjh/v1)
# ------------------------------------------------------------
# [v5] 시나리오 응답에 prologue 추가 — 코스 오프닝 대본(화자 순서·연출 비트는 고정,
#      대사만 region·첫 장소로 생성). default_factory=list라 기존 호출자 무영향.
# 구현일: 2026-09-04 | 작성: ljs (prologue-story-gen/ljs/v1)
# ------------------------------------------------------------
# [v6] 검색 후보에 dist_m 추가 — 앱이 '탐색 반경 먼저' 순서를 지키려면 거리가 필요하다(QA1).
# 구현(요약): 앱이 반경을 먼저 고르고 그 안에서 가고싶은 곳을 고르게 바뀌는데, 검색은
#            키워드 전용이라 전국 아무 곳이나 잡혔다. lat/lng를 주면 거리를 채워 거리순으로
#            주고, radius_m까지 주면 반경 밖은 빼고 준다(routes.search). 좌표 미전송이면
#            dist_m=None으로 기존 동작 그대로(하위호환).
# 구현일: 2026-09-12 | 작성: pjh (wish-dupe-search-radius/pjh/v1)
# ============================================================
from pydantic import BaseModel, Field


class DialogueRequest(BaseModel):
    """NPC 대화 요청 — 게임 서버(dokkaebi-server)가 내부 HTTP로 호출."""

    user_id: str | None = Field(None, description="운영 로그 상관관계용(선택) — 서버가 보내면 로그에 유저가 찍힌다")
    user_name: str | None = Field(None, description="운영 로그 표시용 닉네임(선택)")
    node_id: str = Field(..., description="장소 노드 ID")
    node_name: str = Field("", description="장소 표시명 — 페르소나 합성 입력(8-B)")
    stage: str = Field("등장", description="등장|의뢰|힌트|완료")
    player_state: dict = Field(default_factory=dict, description="진행도·보유 조각·이전 대화 요약")


class DialogueResponse(BaseModel):
    """NPC 대화 응답."""

    response: str
    cache_hit: bool = False


# --- 분기 대화 (찐 RPG, 기획 8-D·7-C) ---
class BranchOptionSchema(BaseModel):
    """갈림길 갈래 1개 — node_sequence[BP].branch.options 원소 그대로."""
    choice_id: str                                       # "main" | "b1" (route_tree 갈래 id)
    label: str = ""
    next_node_id: str = ""


class BranchSchema(BaseModel):
    """갈림길 — 앱이 시나리오 payload에서 꺼내 그대로 실어 보낸다.

    AI는 시나리오를 들고 있지 않아(무상태) 이 값을 받아야 갈림길을 인지할 수 있다.
    """
    prompt: str = ""
    options: list[BranchOptionSchema] = Field(default_factory=list)


class DialogueTurnRequest(BaseModel):
    """분기 대화 한 턴 — 선택마다 호출(멀티턴). 인벤토리로 연계(7-C)."""
    user_id: str | None = None                           # 운영 로그 상관관계용(선택)
    user_name: str | None = None                         # 운영 로그 표시용 닉네임(선택)
    node_id: str
    node_name: str = ""
    region_id: str = ""                                  # grounding 재조회 시 지역 워킹셋 편입에 사용
    history: list[dict] = Field(default_factory=list)   # [{role, text}] role=npc|me
    inventory: dict = Field(default_factory=dict)        # {items:[...]} 누적 단서·조각
    last_choice: str | None = None                       # 직전 선택 id('collect'·'main'·'b1'이면 종료)
    turn: int = 0                                        # 대화 깊이(상한 초과 시 수렴)
    fragment_id: str | None = None                       # 이 노드 조각 id(의뢰 문구에 사용)
    branch: BranchSchema | None = None                   # 갈림길 노드면 채워 보낸다(ai#24 연계)
    player_state: dict = Field(default_factory=dict)     # {progress, required} 진행도 — 대사 톤 조절
    kind: str = "spot"                                   # spot|food|cafe — 식음이면 조각 의뢰 대신 요기 권유


class Choice(BaseModel):
    """선택지 1개. 갈림길 노드에서는 id가 곧 route 갈래 id(main|b1)다 —
    앱은 이 값을 서버 `POST /runs/{runId}/nodes/{nodeId}/complete`의 choice_id로 넘긴다."""
    id: str
    text: str


class DialogueTurnResponse(BaseModel):
    """분기 대화 응답 — 대사 + 선택지 + 획득물 + 종료여부."""
    response: str
    choices: list[Choice] = Field(default_factory=list)
    grants: list[str] = Field(default_factory=list)      # 획득한 조각/단서 id
    done: bool = False                                   # 이 노드 대화 완료(→ AR 탐색으로)


# --- 시나리오 생성 (입력 contract = 아키텍처 5-6) ---
class LatLngSchema(BaseModel):
    """좌표(앱이 GPS/카카오로 해석해 넘김)."""
    lat: float
    lng: float


class WishItemSchema(BaseModel):
    """위시리스트 항목 — searchKeyword2 자동완성에서 확정된 content_id."""
    content_id: str
    name: str | None = None                              # 표시용(합성 앵커 이름)
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
    budget: int | None = None                            # 일행 전체 예상 지출 상한
    headcount: int = Field(1, ge=1, description="인원수. 1인 예산 = budget/headcount")
    no_meals: bool = False                               # '밥 안 먹음' → 식음 노드 skip
    region: str = "auto"                                 # "auto"면 후보 주소에서 시군구 유추
    duration: str = Field("2h", description="2h|half|full — 노드 수·반경 배율")
    companion: str = Field("solo", description="solo|friend|couple|family — 인원수 산출")
    difficulty: str = Field("normal", description="easy|normal|hard — 트리거 반경·힌트 수")
    tags: list[str] = Field(default_factory=list, description="취향 태그 — 후보 선호 가중")
    use_fixed_script: bool = Field(False, description="종로 정답지 고정 재생(시연용)")
    with_dialogue: bool = True
    with_content: bool = True
    with_branching: bool = False        # 갈림길(route 분기) 트리 생성(#24). 기본 off=선형


class PrologueLineSchema(BaseModel):
    """프롤로그 대본 한 줄. speaker=beat면 text 없이 연출 트리거(beat)만 채워진다."""
    speaker: str                                          # narration | npc | player | beat
    text: str = ""
    beat: str | None = None                                # speaker=="beat"일 때만(reach|reveal|recoil|longing)


class ScenarioGenResponse(BaseModel):
    """시나리오 생성 응답(노드 시퀀스 + 메타). node_sequence는 퀘스트 dict 배열."""
    scenario_id: str
    title: str
    region: str
    type: str = "custom"
    node_sequence: list[dict]
    stone_total: int | None = None      # 기억석 조각 총수(식음 노드 제외)
    anchor_node_id: str | None = None
    is_public: bool = False
    created_by: str | None = None
    budget: int | None = None
    headcount: int = 1                  # 요청 인원수(예산 게이팅 근거) — 저장·검증용
    transport: str = "walk"             # 요청 이동수단(반경 산출 근거) — 저장·검증용
    duration: str = "2h"                # 요청 탐험 시간(노드 수·반경 근거) — 저장·검증용
    companion: str = "solo"             # 요청 동행(인원수 근거) — 저장·검증용
    difficulty: str = "normal"          # 요청 난이도(트리거 반경·힌트 수 근거) — 저장·검증용
    tags: list[str] = Field(default_factory=list)   # 요청 취향 태그 — 저장·검증용
    wishlist_content_ids: list[str] = Field(default_factory=list)  # 위시 앵커 content_id(앱 표시용)
    is_branching: bool = False          # 갈림길 포함 여부(선형이면 False)
    route_tree: dict | None = None      # 분기 그래프(node_id→{next, choices}). 선형이면 None
    # 생성 품질 경고(A1 QA 루프가 못 고친 결함·미션 제네릭 폴백). 정상 생성이면 [].
    # 하위호환: 기존 호출자는 이 키를 몰라도 되고, 없으면 빈 배열로 나간다.
    qa_flags: list[str] = Field(default_factory=list)
    # 코스 오프닝 프롤로그 대본(화자 순서·연출 비트 고정, 대사만 region·첫 장소로 생성).
    # 하위호환: 없으면 빈 배열 — 앱은 이 경우 자체 정적 텍스트로 폴백.
    prologue: list[PrologueLineSchema] = Field(default_factory=list)


# --- 관광지 검색 (앵커 자동완성) ---
class SearchCandidate(BaseModel):
    """검색 후보 1개 — 앱 자동완성 드롭다운 항목."""
    content_id: str
    name: str | None = None
    addr: str | None = None
    lat: float | None = None
    lng: float | None = None
    # 현재 위치에서의 직선거리(m). 요청에 lat·lng가 있을 때만 채워진다 — 앱이 "3km 이내"
    # 같은 표시·정렬에 그대로 쓴다. 좌표를 안 보내면 None(기존 호출자 무영향).
    dist_m: float | None = None


class SearchResponse(BaseModel):
    """관광지 이름 검색 결과.

    좌표를 안 보내면 정확 일치 우선 정렬(기존), 보내면 거리순 정렬 + dist_m 채움.
    radius_m까지 보내면 반경 밖 후보는 아예 빠진다(앱의 '반경 먼저' 순서 지원).
    """
    candidates: list[SearchCandidate]


# --- 내 주변 탐험 (좌표 기반 POI 목록) ---
class NearbyPlace(BaseModel):
    """내 주변 POI 1개 — 코스 생성 없이 그 자리에서 바로 탐색할 수 있는 지점."""
    node_id: str
    name: str | None = None
    addr: str | None = None
    lat: float | None = None
    lng: float | None = None
    dist_m: float | None = None
    # historic | museum | artwork | viewpoint | park | attraction | other
    # 앱이 아이콘·필터칩에 그대로 쓴다(osm._category_of가 이 6종으로 좁힌다).
    category: str = "other"
    # 장소 설명 한 줄 요약(TourAPI detailCommon2 overview 앞부분). 없으면 None.
    summary: str | None = None


class NearbyResponse(BaseModel):
    """현재 위치 반경 내 POI(거리순). 시나리오 생성과 달리 LLM을 타지 않아 즉시 응답."""
    places: list[NearbyPlace]


# --- 사진 검증 (PHOTO_FIND·PATH_TRACE 촬영 미션 완료 판정) ---
class PhotoVerifyRequest(BaseModel):
    """플레이어 사진 1장 + 그 노드의 참조 사진(photo_refs.ref_image) → 같은 대상인지 판정."""
    user_id: str | None = Field(None, description="운영 로그 상관관계용(선택)")
    user_name: str | None = None
    node_id: str
    node_name: str = Field("", description="장소명 — 프롬프트·글자 대조에 쓴다")
    target: str = Field(..., description="찍어야 했던 것 (photo_targets[i])")
    ref_images: list[str] = Field(default_factory=list, description="TourAPI 참조 사진 URL (photo_refs[].ref_image)")
    aliases: list[str] = Field(default_factory=list, description="다른 이름·한자 (예: 興化門). 글자 대조용")
    image_b64: str = Field(..., description="플레이어 사진 — data URI 또는 순수 base64(JPEG)")
    mime: str = Field("image/jpeg")


class PhotoVerifyResponse(BaseModel):
    """verified=None 은 '판정 불가(모델 장애·형식 오류)' — 앱은 행위 완료로 폴백한다."""
    verified: bool | None
    mode: str                              # vision | unverified
    confidence: float = 0.0
    text_seen: str = ""
    reason: str = ""
    npc_line: str
    refs_used: int = 0

