# ============================================================
# [v1] API 라우트 — 대화·시나리오 엔드포인트
# pipeline: AI 백엔드 / 서빙 레이어 (진입점)
# 구현(요약): POST /v1/dialogue · POST /v1/scenarios · GET /v1/health
# 구현일: 2026-06-10 (시나리오 추가: 2026-06-18) | 작성: kys
# ------------------------------------------------------------
# [v2] headcount(인원수)를 ScenarioRequest로 전달 — 식음 예산 게이팅 배선(기본 1).
# 구현일: 2026-08-12 | 작성: pjh (ai-logic-fix/pjh/v2)
# ------------------------------------------------------------
# [v3] 앱 마법사 입력(duration·companion·difficulty·tags·use_fixed_script) 전달.
# 구현일: 2026-08-18 | 작성: kys (explore-input-wiring/kys/v1)
# ============================================================
from fastapi import APIRouter

from app.api.schemas import (
    DialogueRequest,
    DialogueResponse,
    DialogueTurnRequest,
    DialogueTurnResponse,
    NearbyPlace,
    NearbyResponse,
    ScenarioGenRequest,
    ScenarioGenResponse,
    SearchCandidate,
    SearchResponse,
)
from app.scenario.generator import generate_scenario
from app.scenario.request import LatLng, ScenarioRequest, WishItem
from app.services.branching_service import run_branching
from app.services.dialogue_service import run_dialogue
from app.tourapi.client import TourAPIClient

router = APIRouter(prefix="/v1", tags=["ai"])

_tour = TourAPIClient()


@router.post("/dialogue", response_model=DialogueResponse)
async def dialogue(req: DialogueRequest) -> DialogueResponse:
    """[엔드포인트] NPC 대화 생성 — 게임 서버 내부 호출용."""
    text, hit = await run_dialogue(req.node_id, req.stage, req.player_state, node_name=req.node_name)
    return DialogueResponse(response=text, cache_hit=hit)


@router.post("/dialogue/turn", response_model=DialogueTurnResponse)
async def dialogue_turn(req: DialogueTurnRequest) -> DialogueTurnResponse:
    """[엔드포인트] 분기 대화 한 턴 — 대사+선택지(또는 조각 획득). 선택마다 호출."""
    out = await run_branching(
        node_id=req.node_id, node_name=req.node_name, region_id=req.region_id,
        history=req.history, inventory=req.inventory, last_choice=req.last_choice,
        turn=req.turn, fragment_id=req.fragment_id, player_state=req.player_state,
        kind=req.kind,
        branch=req.branch.model_dump() if req.branch else None,
    )
    return DialogueTurnResponse(**out)


@router.post("/scenarios", response_model=ScenarioGenResponse)
async def scenarios(req: ScenarioGenRequest) -> ScenarioGenResponse:
    """[엔드포인트] 시나리오 생성 — 게임 서버가 앱 입력을 전달해 호출."""
    sreq = ScenarioRequest(
        user_id=req.user_id,
        start=LatLng(lat=req.start.lat, lng=req.start.lng),
        end=LatLng(lat=req.end.lat, lng=req.end.lng) if req.end else None,
        radius_m=req.radius_m,
        transport=req.transport,
        wishlist=[WishItem(content_id=w.content_id, name=w.name, lat=w.lat, lng=w.lng, kind=w.kind) for w in req.wishlist],
        budget=req.budget,
        headcount=req.headcount,
        no_meals=req.no_meals,
        region=req.region,
        duration=req.duration,
        companion=req.companion,
        difficulty=req.difficulty,
        tags=list(req.tags),
        use_fixed_script=req.use_fixed_script,
        with_dialogue=req.with_dialogue,
        with_content=req.with_content,
        with_branching=req.with_branching,
    )
    scn = await generate_scenario(sreq)
    return ScenarioGenResponse(**scn)


@router.get("/search", response_model=SearchResponse)
async def search(keyword: str, content_type_id: int = 12, top_n: int = 8) -> SearchResponse:
    """[엔드포인트] 관광지 이름 검색 — 앵커 자동완성(부분일치, 정확 title 우선)."""
    cands = await _tour.search_keyword(keyword, content_type_id, top_n)
    return SearchResponse(candidates=[
        SearchCandidate(
            content_id=str(c["tour_content_id"]), name=c.get("name"),
            addr=c.get("addr"), lat=c.get("map_y"), lng=c.get("map_x"),
        )
        for c in cands
    ])


@router.get("/nearby", response_model=NearbyResponse)
async def nearby(lat: float, lng: float, radius_m: int = 2000, top_n: int = 20) -> NearbyResponse:
    """[엔드포인트] 내 주변 POI 목록(거리순) — "내 주변 탐험" 탭.

    시나리오 생성(/scenarios)과 달리 LLM·경로계산을 타지 않아 즉시 응답한다.
    앱은 이 목록에서 한 곳을 골라 그 자리에서 바로 AR 탐색에 들어간다.
    """
    nodes = await _tour.location_based_list(lng, lat, radius_m)
    return NearbyResponse(places=[
        NearbyPlace(
            node_id=str(n.get("node_id")), name=n.get("name"),
            addr=n.get("addr1"), lat=n.get("map_y"), lng=n.get("map_x"),
            dist_m=n.get("dist_m"), category=n.get("category") or "other",
        )
        for n in nodes[:top_n]
    ])


@router.get("/health")
async def health() -> dict:
    """[엔드포인트] 헬스체크."""
    return {"status": "ok"}
