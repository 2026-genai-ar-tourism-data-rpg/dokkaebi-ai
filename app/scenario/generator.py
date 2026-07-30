# ============================================================
# [v1] 시나리오 생성기 — 거리순 기억석 챕터 (v0) + 장소기반 NPC 대사
# pipeline: AI 백엔드 / 시나리오 (노드 선택+배열 → grounding 대사 → 퀘스트 조립)
# 구현(요약): 거리순 N개 → detailCommon2 overview 보강 → 지역캐시 워밍 →
#            대화 그래프(run_dialogue)로 장소기반 LLM 대사 → 기억석 챕터 조립.
#            with_dialogue=False면 고정 대사(토큰 절약). 노드선택(앵커+샛길)·재사용은 추후.
# 구현일: 2026-06-18 | 작성: kys (scenario-mvp/kys/v1)
# ------------------------------------------------------------
# [v2] 식음노드 기억석 오인 방지 — 조각 번호/total/피날레를 '관광 노드'만 기준으로 계산.
# 구현(요약): route에 섞인 kind=food/cafe(정찬희 hook 삽입)를 기억석 조각에서 제외.
#            _plan_nodes가 노드별 역할(조각 번호·피날레·식음) 메타 부여 → 대사/미션/조립이 이를 사용.
#            식음노드 = 경유/보상 퀘스트(대사 O, 기억석 미션·fragment_id X).
# 구현일: 2026-07-05 | 작성: kys+pjh (quest-foodnode/kys-pjh/v1)
# ============================================================
import asyncio
import hashlib
from app.config import get_settings
from app.core.exceptions import DokkaebiAIError
from app.core.logger import get_logger
from app.region.memory_cache import get_region_cache
from app.scenario.density import density_label
from app.scenario.node_content import assign_mission_type, generate_mission, to_quiz
from app.scenario.node_schema import enrich_quest, link_state_graph
from app.scenario.request import ScenarioRequest
from app.scenario.route_branching import attach_branch, pick_alternate, select_branch_point, validate_tree
from app.scenario.route_builder import build_route
from app.services.dialogue_service import run_dialogue
from app.tourapi.client import TourAPIClient
logger = get_logger(__name__)
# 핫패스 공용 TourAPI 클라이언트 (키 없으면 mock)
_tour = TourAPIClient()

# LLM 대사 실패/비활성 시 폴백 고정 대사(도깨비 말투)
_FIXED = "{name}에 깃든 기억의 조각이 어딘가 숨었느니라. 눈을 크게 뜨고 찾아보거라."
_FIXED_FINALE = "오호, 마지막 조각이로다! {name}에서 흩어진 기억을 모두 모아 복원하거라!"
_FIXED_FOOD = "{name}에서 잠시 요기를 하고 가거라. 배가 든든해야 기억도 잘 떠오르는 법이지."
# 식음 삽입 노드(정찬희 hook)의 마커 — 기억석 조각이 아님(경유/보상 노드)
_FOOD_KINDS = ("food", "cafe")


def _is_food(node: dict) -> bool:
    """식음(카페·식당) 삽입 노드인가. True면 기억석 조각·fragment_id 대상에서 제외."""
    return node.get("kind") in _FOOD_KINDS


def _plan_nodes(route: list[dict]) -> list[dict]:
    """route 각 노드에 역할 메타 부여 — 조각 번호/피날레는 '관광 노드'만 기준.
    반환[i] = {is_food, is_finale, stone_no(1-base|None), stone_index(0-base|None), stone_total}.
    식음노드는 조각 번호 없음(None) → fragment_id 안 붙고 total에도 안 잡힘.
    피날레 = 마지막 '관광' 노드(식음이 뒤에 붙어도 관광 노드가 피날레).
    """
    stone_total = sum(1 for n in route if not _is_food(n))
    finale_idx = max((i for i, n in enumerate(route) if not _is_food(n)), default=-1)
    metas: list[dict] = []
    stone_no = 0
    for i, n in enumerate(route):
        if _is_food(n):
            metas.append({"is_food": True, "is_finale": False,
                          "stone_no": None, "stone_index": None, "stone_total": stone_total})
        else:
            stone_no += 1
            metas.append({"is_food": False, "is_finale": i == finale_idx,
                          "stone_no": stone_no, "stone_index": stone_no - 1,
                          "stone_total": stone_total})
    return metas

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
        with_branching=req.with_branching,
    )
    # 입력 메타 부착(저장·검증용)
    scn["created_by"] = req.user_id
    scn["budget"] = req.budget
    scn["transport"] = req.transport
    # wishlist 앵커 강제포함은 route_builder.build_route(① 단계, 정찬희)가 처리. 여기선 메타만.
    if req.wishlist:
        scn["wishlist_content_ids"] = [w.content_id for w in req.wishlist]
    return scn

async def generate_basic_scenario(
    map_x: float, map_y: float, *, region: str = "종로",
    radius_m: int | None = None, count: int | None = None,
    with_dialogue: bool = True, with_content: bool = True,
    end_x: float | None = None, end_y: float | None = None,
    wishlist: list | None = None, budget: int | None = None, no_meals: bool = False,
    with_branching: bool = False,
) -> dict:
    """[거리순 v0] 가까운 N개 관광지로 '기억석 챕터' 생성 + 장소기반 NPC 대사.
    map_x=경도, map_y=위도. end_x/y 주면 끝점에 가장 가까운 노드를 피날레로.
    with_dialogue=True면 각 노드 LLM 대사(그래프) 생성.
    노드 선택/배열(앵커·비인기·식음)은 route_builder.build_route로 분리 — hook별 오너:
    위시=정찬희 / 비인기=이지선 / 식음=박준형 / 분기·seam=김예슬.
    route에 섞인 식음노드(kind=food/cafe)는 기억석 조각이 아님 → _plan_nodes가 분리.
    """
    s = get_settings()
    radius_m = radius_m or s.scenario_default_radius_m
    count = count or s.scenario_node_count
    # 1) 반경 내 관광지 거리순 fetch
    nodes = await _tour.location_based_list(map_x, map_y, radius_m, content_type_id=s.scenario_content_type_id)
    if not nodes and not wishlist:
        raise DokkaebiAIError(f"반경 {radius_m}m 내 관광지 없음 (좌표 {map_x},{map_y})")
    if not nodes:
        logger.warning("반경 내 후보 없음 → 위시 앵커만으로 경로 구성")
    # 1.5) 노드 선택/배열 seam — 앵커 강제포함 + 거리순 채우기 + 피날레 + 식음 삽입
    route = build_route(
        nodes, count=count, start_x=map_x, start_y=map_y, end_x=end_x, end_y=end_y,
        wishlist=wishlist, budget=budget, no_meals=no_meals,
        lowtraffic_k=s.scenario_lowtraffic_anchors,
    )
    # 노드 역할 메타(조각 번호·피날레·식음 분리). total은 '관광 노드'만 셈.
    metas = _plan_nodes(route)
    stone_total = metas[0]["stone_total"] if metas else 0
    # 2) 각 노드 overview 보강 (mock=내장 / 실데이터=detailCommon2 병렬)
    overviews = await asyncio.gather(*[_overview_for(n) for n in route])
    for n, ov in zip(route, overviews):
        n["overview"] = ov or ""

    # 3) 지역 인메모리 캐시 워밍 → 대화 그래프 context_load가 이 텍스트를 grounding으로 사용
    get_region_cache().warm(region, {n["node_id"]: n["overview"] for n in route})
    # 4) 장소기반 NPC 대사 생성 (그래프 재사용, 병렬). 실패/비활성 시 고정 대사
    if with_dialogue:
        dialogues = await asyncio.gather(*[_dialogue_for(n, m) for n, m in zip(route, metas)])
    else:
        dialogues = [_fixed(n, m) for n, m in zip(route, metas)]
    # 4.5) 고정 콘텐츠(생성 시 1회): 비인기 라벨(mock) + 퀴즈·지령(LLM, grounding). 아키텍처 3-5
    for n, m in zip(route, metas):
        if not m["is_food"]:                  # 식음노드는 비인기 라벨 대상 아님
            n["density_tier"] = density_label(n)  # mock — 실데이터는 빅데이터 task
    # 노드마다 미션 타입을 다양화(P1-P6 카탈로그): 순환 배정 + 피날레=복원. 식음노드는 미션 없음(None)
    if with_content:
        missions = await asyncio.gather(
            *[_content_for(n, m) for n, m in zip(route, metas)]
        )
    else:
        missions = [None] * len(route)
    logger.info("거리순 시나리오: 후보 %d → 관광 %d조각 + 식음 %d (반경 %dm, 대사=%s, 미션=%s)",
                len(nodes), stone_total, len(route) - stone_total, radius_m,
                "LLM" if with_dialogue else "고정",
                "/".join(m["type"] for m in missions if m) if with_content else "OFF")
    # 5) 퀘스트 조립 — order=방문 순서(식음 포함), fragment는 관광 노드만
    node_sequence = [
        _build_quest(n, i, metas[i], region, dialogues[i], mission=missions[i])
        for i, n in enumerate(route)
    ]
    finale_id = next((q["node_id"] for q in reversed(node_sequence) if q["is_finale"]),
                     route[-1]["node_id"])
    # 6) [route 분기] 선형 → 트리(다이아몬드). 본선 위에 갈림길 1곳을 얹고 재합류(#24).
    #    결정=eager(생성시 유계 트리 확정) · 근거 docs/route-branching.md. off면 선형 그대로.
    is_branching = False
    route_tree = None
    if with_branching:
        node_sequence, route_tree = await _apply_branching(
            node_sequence, route, nodes, region,
            with_dialogue=with_dialogue, with_content=with_content,
        )
        is_branching = route_tree is not None
    node_sequence = link_state_graph(node_sequence)
    return {
        "scenario_id": _make_scenario_id(region, [q["node_id"] for q in node_sequence]),
        "title": f"{region}의 기억석 — {stone_total}조각 코스",
        "region": region,
        "type": "custom",
        "node_sequence": node_sequence,
        "stone_total": stone_total,               # 기억석 조각 총수(식음 제외)
        "anchor_node_id": finale_id,              # 피날레 = 마지막 관광 노드
        "is_public": False,
        "is_branching": is_branching,             # 갈림길(route 분기) 포함 여부
        "route_tree": route_tree,                 # 분기 그래프(선택→다음 노드). 선형이면 None
    }

async def _apply_branching(
    node_sequence: list[dict], route: list[dict], candidates: list[dict], region: str, *,
    with_dialogue: bool, with_content: bool,
) -> tuple[list[dict], dict | None]:
    """본선 node_sequence에 갈림길 1곳을 얹어 다이아몬드 트리로 만든다(재합류).
    ① 분기 노드 선택 → ② 예비 후보에서 샛길 노드 픽 → ③ 샛길 노드 콘텐츠(대사·미션) 생성
    → ④ attach_branch로 트리 조립. 조건 미충족(짧은 경로·예비 없음)이면 (선형, None) 반환.
    샛길 노드는 기억석 조각 수(stone_total)에 넣지 않음 — 본선 M의 '대안'이라서(MVP 결정).
    """
    bp_i = select_branch_point(node_sequence)
    if bp_i is None:
        logger.info("route 분기 skip: 분기 지점 없음(경로 짧음)")
        return node_sequence, None
    used = {q["node_id"] for q in node_sequence}
    reserve = [n for n in candidates if n["node_id"] not in used and not _is_food(n)]
    alt_src = pick_alternate(node_sequence, reserve, bp_i)
    if alt_src is None:
        logger.info("route 분기 skip: 샛길 예비 후보 없음")
        return node_sequence, None
    # 샛길 노드 콘텐츠 — 본선 M과 동급의 관광 노드로 취급(등장 대사 + 미션 1개)
    alt_meta = {"is_food": False, "is_finale": False, "stone_no": None,
                "stone_index": max(0, bp_i), "stone_total": 0}
    alt_src["overview"] = await _overview_for(alt_src) or ""
    get_region_cache().warm(region, {alt_src["node_id"]: alt_src["overview"]})
    alt_dialogue = await _dialogue_for(alt_src, alt_meta) if with_dialogue else _fixed(alt_src, alt_meta)
    alt_mission = await _content_for(alt_src, alt_meta) if with_content else None
    alt_quest = _build_branch_quest(alt_src, len(node_sequence), region, alt_dialogue, alt_mission)
    seq2, tree = attach_branch(node_sequence, bp_i, alt_quest)
    try:
        validate_tree(tree)                    # 무결성·수렴 방어 — 깨진 트리는 선형 폴백
    except AssertionError as e:
        logger.warning("route 분기 검증 실패 → 선형 폴백: %s", e)
        return node_sequence, None
    return seq2, tree


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

async def _dialogue_for(node: dict, meta: dict) -> str:
    """대화 그래프로 장소기반 대사 생성. 식음=요기 권유, 관광=등장/완료. 실패 시 고정 대사 폴백."""
    stage = "식음" if meta["is_food"] else ("완료" if meta["is_finale"] else "등장")
    try:
        text, _hit = await run_dialogue(node["node_id"], stage, {})
        return text or _fixed(node, meta)
    except Exception as e:  # LLM 오류 등 → 시나리오 생성 자체는 막지 않음
        logger.warning("노드 %s 대사 생성 실패 → 고정 대사: %s", node.get("node_id"), e)
        return _fixed(node, meta)

def _fixed(node: dict, meta: dict) -> str:
    """폴백 고정 대사. 식음노드는 요기 권유, 그 외는 조각/피날레 대사."""
    if meta["is_food"]:
        tmpl = _FIXED_FOOD
    else:
        tmpl = _FIXED_FINALE if meta["is_finale"] else _FIXED
    return tmpl.format(name=node.get("name", "이곳"))


async def _content_for(node: dict, meta: dict) -> dict | None:
    """관광 노드 미션 생성(타입별 다양화). 식음노드는 기억석 미션 없음(None).
    실패해도 시나리오 안 막음(폴백 보장). 미션 타입 순환은 '조각 순서'(stone_index) 기준.
    """
    if meta["is_food"]:
        return None                        # 식음노드 = 경유/보상, 기억석 미션 아님
    name, overview = node.get("name") or "이곳", node.get("overview") or ""
    mtype = assign_mission_type(meta["stone_index"], is_finale=meta["is_finale"])
    try:
        return await generate_mission(name, overview, mtype)
    except Exception as e:
        logger.warning("노드 %s 미션 생성 실패: %s", node.get("node_id"), e)
        return {"type": mtype, "order": f"{name} 주변을 살펴 기억석 조각을 찾아라.",
                "hints": ["주변을 둘러보거라."]}

def _build_quest(node: dict, order: int, meta: dict, region: str, dialogue: str,
                 mission: dict | None = None) -> dict:
    """노드 1개 → 퀘스트 1개. order=방문 순서(식음 포함). 식음노드는 경유/보상 퀘스트로 분기.

    관광 노드: 도착→NPC대사→미션(타입별)→기억석 조각1→다음, 마지막=피날레(fragment_id 부여).
    식음 노드: 대사만(요기 권유)+쿠폰. 기억석 미션·fragment_id 없음 → 조각으로 오인 안 됨.
    """
    if meta["is_food"]:
        return _build_food_quest(node, order, dialogue)
    objective = None
    quiz = None
    if mission:
        objective = {"order": mission.get("order", ""), "hints": mission.get("hints", [])}
        quiz = to_quiz(mission)
    quest = {
        "order": order,
        "node_id": node["node_id"],
        "name": node.get("name"),
        "kind": "spot",          # 기억석 관광 노드
        "map_x": node.get("map_x"), "map_y": node.get("map_y"),
        "dist_m": node.get("dist_m"),
        "density_tier": node.get("density_tier"),
        "mission": mission,      # 타입별 미션(생성 시 1회). 핵심: 노드마다 다른 종류
        "quiz": quiz,            # 앱 호환: 질문형이면 채워짐, 아니면 None
        "objective": objective,  # AR 지령 + 단계 힌트(모든 타입 공통)
        "trigger_radius_m": 100,                         # 개방공간 기본(노드 상세 붙으면 교체)
        "stone_no": meta["stone_no"],                    # 기억석 조각 번호(1-base)
        "fragment_id": f"{region}_stone_{meta['stone_no']}of{meta['stone_total']}",
        "npc_dialogue": dialogue,
        "is_finale": meta["is_finale"],
    }
    return enrich_quest(quest, node)

def _build_food_quest(node: dict, order: int, dialogue: str) -> dict:
    """식음(카페·식당) 경유 퀘스트. 기억석 아님 — fragment_id/미션 없음, 쿠폰·가격밴드만."""
    quest = {
        "order": order,
        "node_id": node["node_id"],
        "name": node.get("name"),
        "kind": node.get("kind"),                        # "food" | "cafe"
        "map_x": node.get("map_x"), "map_y": node.get("map_y"),
        "dist_m": node.get("dist_m"),
        "price_band": node.get("price_band") or node.get("band"),
        "price_band_label": node.get("price_band_label"),
        "coupon": node.get("coupon"),                    # 상권 쿠폰(food hook 부착)
        "mission": None,
        "quiz": None,
        "objective": None,
        "trigger_radius_m": 100,
        "fragment_id": None,                             # ★ 기억석 조각 아님
        "npc_dialogue": dialogue,
        "is_finale": False,
    }
    return enrich_quest(quest, node)

def _build_branch_quest(node: dict, order: int, region: str, dialogue: str,
                        mission: dict | None = None) -> dict:
    """샛길(분기 대안) 관광 퀘스트. 본선 M의 대안이라 stone_no 없음·total에 안 잡힘.
    관광 노드와 동일한 플레이(도착→대사→미션→조각) — 단 fragment는 분기 전용 id.
    실제 방문 순서는 route_tree가 정의(order는 안정 인덱스일 뿐).
    """
    objective = quiz = None
    if mission:
        objective = {"order": mission.get("order", ""), "hints": mission.get("hints", [])}
        quiz = to_quiz(mission)
    quest = {
        "order": order,
        "node_id": node["node_id"],
        "name": node.get("name"),
        "kind": "spot",
        "path_id": "b1",                                 # 샛길 갈래
        "map_x": node.get("map_x"), "map_y": node.get("map_y"),
        "dist_m": node.get("dist_m"),
        "density_tier": node.get("density_tier"),
        "mission": mission,
        "quiz": quiz,
        "objective": objective,
        "trigger_radius_m": 100,
        "stone_no": None,                                # 조각 번호 없음(본선 대안)
        "fragment_id": f"{region}_branch_b1",
        "npc_dialogue": dialogue,
        "is_finale": False,
    }
    return enrich_quest(quest, node)

def _make_scenario_id(region: str, node_ids: list[str]) -> str:
    """노드 구성으로 결정적 시나리오 ID(같은 구성=같은 ID → 재사용 키 기반)."""
    digest = hashlib.sha256("|".join(node_ids).encode()).hexdigest()[:8]
    return f"scn_{region}_{digest}"