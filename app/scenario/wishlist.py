# ============================================================
# [v1] 위시리스트 앵커 선택 — build_route ① 단계 hook (현재 STUB)
# pipeline: AI 백엔드 / 시나리오 (사용자 '꼭 가고싶은 곳'을 경로에 강제 포함)
# 구현(요약): ⚠️ STUB. 지금은 [] 반환 → build_route가 거리순으로만 동작(기존과 동일).
#            담당 이지선: 반경 내 후보(nodes)에서 wishlist의 content_id 매칭분을 앵커로,
#            반경 밖이면 wishlist 좌표(lat/lng)로 합성 노드 생성해 강제 포함.
# 구현일: 2026-06-23 | 작성: kys (route-seam/kys/v1)
# 관련: 기획 11-3 앵커+샛길 · request.py WishItem · route_builder.build_route
# ============================================================


def select_wishlist_anchors(nodes: list[dict], wishlist: list) -> list[dict]:
    """[STUB → 이지선] 위시리스트를 경로 앵커(강제포함) 노드 리스트로 변환.

    nodes: 반경 내 거리순 후보. wishlist: list[WishItem](content_id 확정분).
    반환: 경로에 반드시 들어갈 노드 dict 리스트(node_id 키 필수). 지금은 빈 리스트.

    TODO(이지선):
      1) content_id로 nodes에서 매칭 → 그 노드를 앵커로
      2) nodes에 없으면(반경 경계 밖 등) WishItem.lat/lng로 합성 노드 생성
         {node_id: f"wish_{content_id}", name, map_x, map_y, dist_m, source:"wishlist"}
      3) kind=="restaurant"는 식음 단계(정찬희)와 중복 안 되게 정책 합의
    """
    return []
