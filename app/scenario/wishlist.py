# ============================================================
# [v1] 위시리스트 앵커 강제포함 — build_route ① 단계 hook
# pipeline: AI 백엔드 / 시나리오 (사용자 '꼭 가고싶은 곳'을 경로에 강제 포함)
# 구현(요약): select_wishlist_anchors(nodes, wishlist) → 위시 content_id를 반경 내
#            노드(tour_content_id)와 매칭하면 그 노드를 앵커로 source 마킹, 매칭 없으면(반경 밖)
#            위시 좌표(lat/lng)로 합성 노드 생성 + WARN. content_id 중복 제거.
#            ⚠️ 분담 표기: WEEKLY-PLAN §2 = 위시 앵커는 '정찬희'. 기존 STUB 헤더의 '이지선'
#               표기는 오기(이지선=비인기 density.py 담당) → 정정은 PR 전 팀 합의.
#            ⚠️ 결정 B/C는 hook 단독으론 미실현 — select_wishlist_anchors docstring NOTE 참조
#               (generator 빈노드 가드 · route_builder 캡은 경계 밖).
# 구현일: 2026-06-30 | 작성: 정찬희 (wishlist-anchor/jch/v1) · seam STUB 최초: kys (route-seam/kys/v1)
# 관련: 기획 11-3 앵커+샛길 · request.py WishItem · route_builder.build_route
# ------------------------------------------------------------
# [v2] 결정 B/C 구현 — 경계(generator·route_builder) 쪽 반영.
# 구현(요약): generator.generate_basic_scenario의 `if not nodes: raise`를
#            `if not nodes and not wishlist: raise`로 완화(B) + route_builder._select_count의
#            `selected[:count]` 캡 제거로 앵커 전부 보존(C). 이 hook 자체는 변경 없음
#            (처음부터 캡 없이 B/C를 반환했음) — 경계 쪽 가드/캡만 따라잡음.
# 구현일: 2026-07-14 | 작성: 정찬희 (radius-edge/jch/v1)
# ------------------------------------------------------------
# [v3] 합성 앵커에 tour_content_id 보존 — 위시 장소가 근거 없이 말하던 것 수정.
# 구현(요약): 합성 노드에 content_id를 안 실어 보내 generator._overview_for가 상세 조회를
#            못 했다. 그 결과 **사용자가 콕 집어 넣은 장소**의 도깨비만 원문 없이 말했다
#            (실측: 경복궁 grounding 0자 → 모델 기억으로 발화). content_id는 이미 손에
#            있으므로 키 하나만 실어 주면 detailCommon2로 원문을 받는다.
# 구현일: 2026-08-19 | 작성: kys (dialogue-rework/kys/v1)
# ============================================================
from app.core.logger import get_logger

logger = get_logger(__name__)

# --- 매직 문자열 상수(단일 소스) ---
SOURCE_WISHLIST = "wishlist"              # 앵커 노드의 source 마킹 값
WISH_NODE_PREFIX = "wish_"                # 합성(반경 밖) 노드 node_id 접두사
NODE_CONTENT_ID_KEY = "tour_content_id"   # 노드 dict에서 TourAPI contentId를 담는 키
OUT_OF_RADIUS_FLAG = "out_of_radius"      # 합성 앵커(반경 밖) 표시 플래그 키


def _node_content_id(node: dict) -> str | None:
    """노드 dict에서 매칭용 content_id(TourAPI contentId)를 문자열로 추출. 없으면 None.

    mock 노드처럼 tour_content_id가 없는 노드는 None → content_id 매칭 대상에서 제외된다.
    """
    raw = node.get(NODE_CONTENT_ID_KEY)
    return str(raw) if raw is not None else None


def _build_content_id_index(nodes: list[dict]) -> dict[str, dict]:
    """반경 내 노드를 content_id → 노드 dict로 인덱싱(O(1) 매칭).

    content_id가 없는 노드는 제외한다. content_id가 겹치면 뒤 노드가 앞 노드를 덮어쓴다
    (거리순 입력에서는 사실상 발생하지 않음).
    """
    index: dict[str, dict] = {}
    for node in nodes:
        cid = _node_content_id(node)
        if cid is not None:
            index[cid] = node
    return index


def _to_anchor(node: dict) -> dict:
    """반경 내 매칭 노드를 위시 앵커로 변환(원본 비파괴 얕은 복사 + source 마킹).

    원본 노드 정보(node_id·name·map_x·map_y·dist_m 등)는 보존하고, source를 위시로
    덮어쓰며 out_of_radius=False로 표시한다. node_id는 그대로라 _fill_distance의
    dedupe(seen=node_id)·거리순 정렬과 호환된다.
    """
    return {**node, "source": SOURCE_WISHLIST, OUT_OF_RADIUS_FLAG: False}


def _synthesize_anchor(content_id: str, name: str | None,
                       lat: float | None, lng: float | None) -> dict:
    """반경 밖(매칭 없음) 위시를 좌표 기반 합성 앵커 노드로 생성.

    name은 WishItem.name(앱 자동완성에서 확정한 표시 이름). 없으면 None.
    dist_m은 origin 좌표가 이 hook에 들어오지 않아 None — 동선화 시 build_route/generator가
    채운다. lat/lng가 None이면 지도 배치 불가한 합성 노드가 된다(WARN → seam에서 드롭).
    """
    return {
        "node_id": f"{WISH_NODE_PREFIX}{content_id}",
        # 원문(overview) 조회 키 — 없으면 이 노드만 grounding 없이 대사가 나간다.
        NODE_CONTENT_ID_KEY: content_id,
        "name": name,            # 앱이 넘긴 표시 이름(없으면 None)
        "map_x": lng,            # 경도(lng) → map_x
        "map_y": lat,            # 위도(lat) → map_y
        "dist_m": None,          # origin 좌표가 hook에 없음 → 배선부에서 산출
        "source": SOURCE_WISHLIST,
        OUT_OF_RADIUS_FLAG: True,
    }


def select_wishlist_anchors(nodes: list[dict], wishlist: list) -> list[dict]:
    """위시리스트 항목을 경로에 강제 포함할 '앵커' 노드 리스트로 변환(build_route ① 단계 hook).

    거리순으로 뽑힌 후보 노드(nodes)와 사용자 위시(wishlist; 각 항목은 WishItem:
    content_id·lat·lng·kind)를 받아 위시마다 앵커를 만든다. 반환 노드는 node_id 키 필수
    (route_builder._fill_distance가 node_id로 dedupe).

    규칙:
      - wishlist가 비면 [] 반환(no-op — 기존 거리순 동선 보존).
      - 위시 content_id가 nodes의 ``tour_content_id``와 매칭되면 그 노드를 앵커로
        채택하고 source="wishlist"로 마킹한다(반경 내, out_of_radius=False).
      - 매칭되는 노드가 없으면(반경 밖) 위시 좌표로 합성 노드를 만든다:
        ``{node_id: "wish_<content_id>", name, map_x, map_y, dist_m,
        source: "wishlist", out_of_radius: True}``. 이때 WARN 로그를 남긴다.
      - content_id가 중복된 위시는 첫 항목만 남기고 제거한다(입력 순서 보존).
      - 앵커 수에 상한(cap)을 두지 않는다(결정 C: count 초과 허용).
      - nodes가 비고 위시만 있으면 전부 합성 앵커로 반환한다(결정 B).

    NOTE(통합 — radius-edge/jch/v1에서 구현 완료, dev PR 대상):
      · 결정 B(반경 내 후보 0개 + 위시 → 위시만): 이 hook은 nodes=[]에서 합성 앵커를
        정상 반환하고, generator.generate_basic_scenario도 ``if not nodes and not wishlist:``
        로 가드를 완화해 build_route까지 통과시킨다 → 결정 B 실현.
      · 결정 C(앵커 수 > count → 전부): 이 hook은 캡 없이 전부 반환하고,
        route_builder._select_count도 ``return selected``(캡 제거)로 앵커를 전부 보존한다
        → 결정 C 실현.

    Args:
        nodes: 거리순 정렬된 후보 노드 dict 리스트. 매칭 키는 ``tour_content_id``.
            (mock 노드는 tour_content_id가 없어 content_id 매칭이 안 됨에 유의.)
        wishlist: WishItem 리스트(확정 content_id 기반). 비면 no-op.

    Returns:
        앵커 노드 dict 리스트(각 항목 node_id 보유). 매칭 앵커와 합성 앵커가 위시 입력
        순서대로 섞여 들어가며 content_id 중복은 제거된다. 매칭이 없으면 합성 앵커만 들어간다.
    """
    if not wishlist:
        logger.debug("위시리스트 없음 → 앵커 없음(거리순 동선 유지)")
        return []

    index = _build_content_id_index(nodes)
    anchors: list[dict] = []
    seen: set[str] = set()
    matched = 0
    synthesized = 0

    for wish in wishlist:
        content_id = str(wish.content_id)
        if content_id in seen:
            logger.debug("중복 위시 content_id=%s → 제거", content_id)
            continue
        seen.add(content_id)

        node = index.get(content_id)
        if node is not None:
            anchors.append(_to_anchor(node))
            matched += 1
            logger.debug(
                "위시 content_id=%s → 반경 내 노드 %s 앵커 채택", content_id, node.get("node_id")
            )
            continue

        # 매칭 없음(반경 밖) → 좌표 합성 앵커 + WARN
        lat, lng = wish.lat, wish.lng
        if lat is None or lng is None:
            logger.warning(
                "위시 content_id=%s 반경 내 매칭 없음 + 좌표 결측(lat=%s, lng=%s) → "
                "합성 앵커 생성하나 지도 배치 불가",
                content_id, lat, lng,
            )
        else:
            logger.warning(
                "위시 content_id=%s 반경 내 매칭 없음 → 좌표 합성 앵커(map_x=%s, map_y=%s)",
                content_id, lng, lat,
            )
        anchors.append(_synthesize_anchor(content_id, wish.name, lat, lng))
        synthesized += 1

    logger.info(
        "위시 앵커 %d개 확정 (매칭 %d, 합성 %d)", len(anchors), matched, synthesized
    )
    return anchors
