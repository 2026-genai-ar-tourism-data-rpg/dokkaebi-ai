# ============================================================
# [v1] 시나리오 생성기 — 거리순 기억석 챕터 (v0) + 장소기반 NPC 대사
# pipeline: AI 백엔드 / 시나리오 (노드 선택+배열 → grounding 대사 → 퀘스트 조립)
# 구현(요약): 거리순 N개 → detailCommon2 overview 보강 → 지역캐시 워밍 →
#            대화 그래프(run_dialogue)로 장소기반 LLM 대사 → 기억석 챕터 조립.
#            with_dialogue=False면 고정 대사(토큰 절약). 노드선택(앵커+샛길)·재사용은 추후.
# 구현일: 2026-06-18 | 작성: kys (scenario-mvp/kys/v1)
# ============================================================
import asyncio
import hashlib

from app.config import get_settings
from app.core.exceptions import DokkaebiAIError
from app.core.logger import get_logger
from app.region.memory_cache import get_region_cache
from app.scenario.density import density_label
from app.scenario.node_content import assign_mission_type, generate_mission, to_quiz
from app.scenario.request import ScenarioRequest
from app.scenario.route_builder import build_route
from app.services.dialogue_service import run_dialogue
from app.tourapi.client import TourAPIClient

logger = get_logger(__name__)

# 핫패스 공용 TourAPI 클라이언트 (키 없으면 mock)
_tour = TourAPIClient()

# LLM 대사 실패/비활성 시 폴백 고정 대사(도깨비 말투)
_FIXED = "{name}에 깃든 기억의 조각이 어딘가 숨었느니라. 눈을 크게 뜨고 찾아보거라."
_FIXED_FINALE = "오호, 마지막 조각이로다! {name}에서 흩어진 기억을 모두 모아 복원하거라!"


async def generate_scenario(req: ScenarioRequest) -> dict:
    """[입력 contract] 사용자 입력(ScenarioRequest) → 시나리오. 서버가 호출하는 진입점.

    transport→반경 자동, end(집)→피날레, wishlist→앵커(생성로직은 추후). 좌표는 앱이 해석해 넘김.
    """
    s = get_settings()
    radius = req.radius_m or (s.scenario_radius_car_m if req.transport == "car" else s.scenario_radius_walk_m)
    end = req.end
    scn = await generate_basic_scenario(
        req.start.lng, req.start.lat, region=req.region, radius_m=radius,
        with_dialogue=req.with_dialogue, with_content=req.with_content,
        end_x=end.lng if end else None, end_y=end.lat if end else None,
        wishlist=req.wishlist, budget=req.budget, no_meals=req.no_meals,
    )
    # 입력 메타 부착(저장·검증용)
    scn["created_by"] = req.user_id
    scn["budget"] = req.budget
    scn["transport"] = req.transport
    # wishlist 앵커 강제포함은 route_builder.build_route(① 단계, 이지선)가 처리. 여기선 메타만.
    if req.wishlist:
        scn["wishlist_content_ids"] = [w.content_id for w in req.wishlist]
    return scn


async def generate_basic_scenario(
    map_x: float, map_y: float, *, region: str = "종로",
    radius_m: int | None = None, count: int | None = None,
    with_dialogue: bool = True, with_content: bool = True,
    end_x: float | None = None, end_y: float | None = None,
    wishlist: list | None = None, budget: int | None = None, no_meals: bool = False,
) -> dict:
    """[거리순 v0] 가까운 N개 관광지로 '기억석 챕터' 생성 + 장소기반 NPC 대사.

    map_x=경도, map_y=위도. end_x/y 주면 끝점에 가장 가까운 노드를 피날레로.
    with_dialogue=True면 각 노드 LLM 대사(그래프) 생성.
    노드 선택/배열(앵커·비인기·식음)은 route_builder.build_route로 분리 — hook별 오너:
    비인기=박준형 / 위시=이지선 / 식음=정찬희 / 분기·seam=김예슬.
    """
    s = get_settings()
    radius_m = radius_m or s.scenario_default_radius_m
    count = count or s.scenario_node_count

    # 1) 반경 내 관광지 거리순 fetch
    nodes = await _tour.location_based_list(map_x, map_y, radius_m, content_type_id=s.scenario_content_type_id)
    if not nodes:
        raise DokkaebiAIError(f"반경 {radius_m}m 내 관광지 없음 (좌표 {map_x},{map_y})")
    # 1.5) 노드 선택/배열 seam — 앵커 강제포함 + 거리순 채우기 + 피날레 + 식음 삽입
    route = build_route(
        nodes, count=count, end_x=end_x, end_y=end_y,
        wishlist=wishlist, budget=budget, no_meals=no_meals,
        lowtraffic_k=s.scenario_lowtraffic_anchors,
    )
    total = len(route)

    # 2) 각 노드 overview 보강 (mock=내장 / 실데이터=detailCommon2 병렬)
    overviews = await asyncio.gather(*[_overview_for(n) for n in route])
    for n, ov in zip(route, overviews):
        n["overview"] = ov or ""

    # 3) 지역 인메모리 캐시 워밍 → 대화 그래프 context_load가 이 텍스트를 grounding으로 사용
    get_region_cache().warm(region, {n["node_id"]: n["overview"] for n in route})

    # 4) 장소기반 NPC 대사 생성 (그래프 재사용, 병렬). 실패/비활성 시 고정 대사
    if with_dialogue:
        dialogues = await asyncio.gather(*[_dialogue_for(n, i, total) for i, n in enumerate(route)])
    else:
        dialogues = [_fixed(n, i, total) for i, n in enumerate(route)]

    # 4.5) 고정 콘텐츠(생성 시 1회): 비인기 라벨(mock) + 퀴즈·지령(LLM, grounding). 아키텍처 3-5
    for n in route:
        n["density_tier"] = density_label(n)  # mock — 실데이터는 빅데이터 task
    # 노드마다 미션 타입을 다양화(P1-P6 카탈로그): 순환 배정 + 피날레=복원
    if with_content:
        missions = await asyncio.gather(
            *[_content_for(n, i, total) for i, n in enumerate(route)]
        )
    else:
        missions = [None] * total

    logger.info("거리순 시나리오: 후보 %d → 채택 %d (반경 %dm, 대사=%s, 미션=%s)",
                len(nodes), total, radius_m, "LLM" if with_dialogue else "고정",
                "/".join(m["type"] for m in missions if m) if with_content else "OFF")

    # 5) 퀘스트 조립
    node_sequence = [
        _build_quest(n, i, total, region, dialogues[i], mission=missions[i])
        for i, n in enumerate(route)
    ]
    return {
        "scenario_id": _make_scenario_id(region, [q["node_id"] for q in node_sequence]),
        "title": f"{region}의 기억석 — {total}조각 코스",
        "region": region,
        "type": "custom",
        "node_sequence": node_sequence,
        "anchor_node_id": route[-1]["node_id"],  # 거리순 v0: 가장 먼 곳 = 피날레
        "is_public": False,
    }


async def _overview_for(node: dict) -> str | None:
    """노드 overview 확보: mock은 내장값, 실데이터는 detailCommon2 호출.

    한 노드 상세 조회가 실패(TourAPI 일시오류·제한)해도 시나리오 전체를 막지 않음 →
    None 반환(그 노드는 grounding 없이 이름만). 담당: 배선 = 정찬희.
    """
    if node.get("overview"):
        return node["overview"]
    try:
        detail = await _tour.detail_common(node.get("tour_content_id"))
        return detail.get("overview") if detail else None
    except Exception as e:  # detailCommon2 실패 → 그 노드만 overview 없이 진행
        logger.warning("노드 %s overview 조회 실패: %s", node.get("node_id"), e)
        return None


async def _dialogue_for(node: dict, index: int, total: int) -> str:
    """대화 그래프로 장소기반 등장/완료 대사 생성. 실패 시 고정 대사 폴백."""
    stage = "완료" if index == total - 1 else "등장"
    try:
        text, _hit = await run_dialogue(node["node_id"], stage, {})
        return text or _fixed(node, index, total)
    except Exception as e:  # LLM 오류 등 → 시나리오 생성 자체는 막지 않음
        logger.warning("노드 %s 대사 생성 실패 → 고정 대사: %s", node.get("node_id"), e)
        return _fixed(node, index, total)


def _fixed(node: dict, index: int, total: int) -> str:
    """폴백 고정 대사."""
    tmpl = _FIXED_FINALE if index == total - 1 else _FIXED
    return tmpl.format(name=node.get("name", "이곳"))


async def _content_for(node: dict, index: int, total: int) -> dict:
    """노드 미션 생성(타입별 다양화). 실패해도 시나리오 안 막음(폴백 보장)."""
    name, overview = node.get("name") or "이곳", node.get("overview") or ""
    mtype = assign_mission_type(index, is_finale=(index == total - 1))
    try:
        return await generate_mission(name, overview, mtype)
    except Exception as e:
        logger.warning("노드 %s 미션 생성 실패: %s", node.get("node_id"), e)
        return {"type": mtype, "order": f"{name} 주변을 살펴 기억석 조각을 찾아라.",
                "hints": ["주변을 둘러보거라."]}


def _build_quest(node: dict, index: int, total: int, region: str, dialogue: str,
                 mission: dict | None = None) -> dict:
    """노드 1개 → 퀘스트 1개. (도착→NPC대사→미션(타입별)→조각1→다음, 마지막=피날레)

    mission: 타입별 콘텐츠(PHOTO/COLLECT/DIALOGUE/FIND/QUIZ). 모든 미션에 지령(order)+힌트.
    앱 호환: 질문형 미션은 quiz로도 매핑(to_quiz), 지령/힌트는 objective로 매핑.
    """
    is_finale = index == total - 1
    objective = None
    quiz = None
    if mission:
        objective = {"order": mission.get("order", ""), "hints": mission.get("hints", [])}
        quiz = to_quiz(mission)
    return {
        "order": index,
        "node_id": node["node_id"],
        "name": node.get("name"),
        "map_x": node.get("map_x"), "map_y": node.get("map_y"),
        "dist_m": node.get("dist_m"),
        "density_tier": node.get("density_tier"),
        "mission": mission,      # 타입별 미션(생성 시 1회). 핵심: 노드마다 다른 종류
        "quiz": quiz,            # 앱 호환: 질문형이면 채워짐, 아니면 None
        "objective": objective,  # AR 지령 + 단계 힌트(모든 타입 공통)
        "trigger_radius_m": 100,                         # 개방공간 기본(노드 상세 붙으면 교체)
        "fragment_id": f"{region}_stone_{index + 1}of{total}",
        "npc_dialogue": dialogue,
        "is_finale": is_finale,
    }


def _make_scenario_id(region: str, node_ids: list[str]) -> str:
    """노드 구성으로 결정적 시나리오 ID(같은 구성=같은 ID → 재사용 키 기반)."""
    digest = hashlib.sha256("|".join(node_ids).encode()).hexdigest()[:8]
    return f"scn_{region}_{digest}"
