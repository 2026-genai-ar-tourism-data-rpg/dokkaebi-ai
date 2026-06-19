# ============================================================
# [v1] API 라우트 — 대화·시나리오 엔드포인트
# pipeline: AI 백엔드 / 서빙 레이어 (진입점)
# 구현(요약): POST /v1/dialogue · POST /v1/scenarios · GET /v1/health
# 구현일: 2026-06-10 (시나리오 추가: 2026-06-18) | 작성: kys
# ============================================================
from fastapi import APIRouter

from app.api.schemas import (
    DialogueRequest,
    DialogueResponse,
    DialogueTurnRequest,
    DialogueTurnResponse,
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
    text, hit = await run_dialogue(req.node_id, req.stage, req.player_state)
    return DialogueResponse(response=text, cache_hit=hit)


@router.post("/dialogue/turn", response_model=DialogueTurnResponse)
async def dialogue_turn(req: DialogueTurnRequest) -> DialogueTurnResponse:
    """[엔드포인트] 분기 대화 한 턴 — 대사+선택지(또는 조각 획득). 선택마다 호출."""
    out = await run_branching(
        node_id=req.node_id, node_name=req.node_name, region_id=req.region_id,
        history=req.history, inventory=req.inventory, last_choice=req.last_choice,
        turn=req.turn, fragment_id=req.fragment_id,
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
        wishlist=[WishItem(content_id=w.content_id, lat=w.lat, lng=w.lng, kind=w.kind) for w in req.wishlist],
        budget=req.budget,
        region=req.region,
        with_dialogue=req.with_dialogue,
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


@router.get("/health")
async def health() -> dict:
    """[엔드포인트] 헬스체크."""
    return {"status": "ok"}
