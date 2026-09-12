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
# ------------------------------------------------------------
# [v4] /v1/search에 좌표·반경을 연다 — 앱 '탐색 반경 먼저' 순서 지원(QA1 선택안).
# 구현(요약): 검색이 키워드 전용이라 반경을 먼저 골라도 전국 아무 곳이나 선택됐다.
#            lat·lng를 주면 dist_m을 채워 거리순으로, radius_m까지 주면 반경 밖을 빼고
#            돌려준다. 더불어 기본 후보 수를 8 → config.scenario_search_top_n(30)으로
#            올린다 — 8건이면 반경 안 장소가 관련도 순위에서 밀려 앱 필터에 아예 안 잡힌다.
#            ⚠️ 서버(dokkaebi-server)가 이 쿼리를 통과시켜야 앱까지 닿는다
#              (scenario.module.ts:150은 keyword만 받고 ai.client.ts:113이 top_n=8 고정).
#              통과 전에도 top_n 기본값 상향은 서버 수정 없이 바로 효과가 있다.
# 구현일: 2026-09-12 | 작성: pjh (wish-dupe-search-radius/pjh/v1)
# ============================================================
import asyncio

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
from app.config import get_settings
from app.core.logger import get_logger
from app.scenario.generator import generate_scenario
from app.scenario.request import LatLng, ScenarioRequest, WishItem
from app.services.branching_service import run_branching
from app.services.dialogue_service import run_dialogue
from app.tourapi.client import TourAPIClient, haversine_m

router = APIRouter(prefix="/v1", tags=["ai"])

logger = get_logger(__name__)
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
async def search(
    keyword: str,
    content_type_id: int = 12,
    top_n: int | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_m: int | None = None,
) -> SearchResponse:
    """[엔드포인트] 관광지 이름 검색 — 앵커 자동완성(부분일치, 정확 title 우선).

    lat·lng를 주면 그 지점 기준 dist_m을 채워 **거리순**으로 돌려준다.
    radius_m까지 주면 반경 밖 후보는 뺀다 — 앱이 '탐색 반경 먼저' 순서를 지키려면
    검색 자체가 반경을 알아야 하기 때문(QA1).
    top_n 미지정 시 config.scenario_search_top_n을 쓴다 — 8건이면 반경 안 장소가
    관련도 순위에서 밀려 앱 필터에 아예 안 잡힌다.
    """
    limit = top_n or get_settings().scenario_search_top_n
    cands = await _tour.search_keyword(keyword, content_type_id, limit)
    items = [
        SearchCandidate(
            content_id=str(c["tour_content_id"]), name=c.get("name"),
            addr=c.get("addr"), lat=c.get("map_y"), lng=c.get("map_x"),
            dist_m=_dist_from(lat, lng, c.get("map_y"), c.get("map_x")),
        )
        for c in cands
    ]
    if lat is None or lng is None:
        return SearchResponse(candidates=items)

    if radius_m is not None:
        inside = [c for c in items if c.dist_m is not None and c.dist_m <= radius_m]
        if len(inside) < len(items):
            # 앱이 "반경 안인데 결과에 없다"를 판단할 근거 — top_n 상한에 걸린 경우를 가린다.
            logger.info(
                "검색 '%s': 후보 %d개 중 반경 %dm 안 %d개(top_n=%d)",
                keyword, len(items), radius_m, len(inside), limit,
            )
        items = inside
    # 좌표 결측 후보는 거리를 알 수 없어 맨 뒤로(기존 거리순 정렬 특성과 동일)
    return SearchResponse(candidates=sorted(
        items, key=lambda c: c.dist_m if c.dist_m is not None else float("inf"),
    ))


def _dist_from(lat: float | None, lng: float | None,
               node_lat: float | None, node_lng: float | None) -> float | None:
    """현재 위치와 후보 좌표의 직선거리(m). 어느 한쪽이라도 없으면 None."""
    if None in (lat, lng, node_lat, node_lng):
        return None
    return round(haversine_m(lat, lng, node_lat, node_lng), 1)


def _one_line_summary(overview: str | None, max_len: int = 60) -> str | None:
    """개요 텍스트를 카드용 한 줄 요약으로 자른다 — 첫 문장 우선, 길면 글자수로 자름."""
    if not overview:
        return None
    text = " ".join(overview.split())
    period = text.find(". ")
    head = text[: period + 1] if 0 <= period < max_len else text
    return head[:max_len].rstrip() + ("…" if len(head) > max_len else "")


@router.get("/nearby", response_model=NearbyResponse)
async def nearby(lat: float, lng: float, radius_m: int = 2000, top_n: int = 20) -> NearbyResponse:
    """[엔드포인트] 내 주변 POI 목록(거리순) — "내 주변 탐험" 탭.

    시나리오 생성(/scenarios)과 달리 LLM·경로계산을 타지 않아 즉시 응답한다.
    앱은 이 목록에서 한 곳을 골라 그 자리에서 바로 AR 탐색에 들어간다.
    설명(summary)은 detailCommon2 캐시를 재사용(_overview_for와 동일 패턴) — 병렬 호출,
    캐시 히트면 TourAPI 재호출 없음.
    """
    nodes = await _tour.location_based_list(lng, lat, radius_m)
    nodes = nodes[:top_n]
    details = await asyncio.gather(
        *[_tour.detail_common(n.get("tour_content_id")) for n in nodes]
    )
    return NearbyResponse(places=[
        NearbyPlace(
            node_id=str(n.get("node_id")), name=n.get("name"),
            addr=n.get("addr1"), lat=n.get("map_y"), lng=n.get("map_x"),
            dist_m=n.get("dist_m"), category=n.get("category") or "other",
            summary=_one_line_summary((d or {}).get("overview")),
        )
        for n, d in zip(nodes, details)
    ])


@router.get("/health")
async def health() -> dict:
    """[엔드포인트] 헬스체크."""
    return {"status": "ok"}
