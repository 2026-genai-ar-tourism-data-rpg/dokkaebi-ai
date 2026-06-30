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


def _synthesize_anchor(content_id: str, lat: float | None, lng: float | None) -> dict:
    """반경 밖(매칭 없음) 위시를 좌표 기반 합성 앵커 노드로 생성.

    WishItem에는 name 필드가 없어 name=None(서버/앱이 detail 조회로 보강 필요).
    dist_m은 origin 좌표가 이 hook에 들어오지 않아 None — 동선화 시 build_route/generator가
    채운다. lat/lng가 None이면 지도 배치 불가한 합성 노드가 된다(WARN).
    """
    return {
        "node_id": f"{WISH_NODE_PREFIX}{content_id}",
        "name": None,            # WishItem에 name 없음 — 배선부/서버가 보강
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

    NOTE(통합 — PR 전 팀 합의 / generator·route_builder는 경계상 수정 금지):
      · 결정 B(반경 내 후보 0개 + 위시 → 위시만): 이 hook은 nodes=[]에서 합성 앵커를
        정상 반환하나, generator.generate_basic_scenario가 ``if not nodes: raise``로
        build_route 호출 전에 막는다 → generator 가드 완화(kys) 없이는 결정 B 미실현.
      · 결정 C(앵커 수 > count → 전부): 이 hook은 캡 없이 전부 반환하나,
        route_builder._fill_distance가 ``selected[:count]``로 잘라낸다 → seam 조정(kys)
        없이는 결정 C 미실현.

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
        anchors.append(_synthesize_anchor(content_id, lat, lng))
        synthesized += 1

    logger.info(
        "위시 앵커 %d개 확정 (매칭 %d, 합성 %d)", len(anchors), matched, synthesized
    )
    return anchors
