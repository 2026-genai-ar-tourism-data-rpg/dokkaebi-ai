# ============================================================
# [v1] TourAPI mock 노드 — 키 없이 거리순 로직 검증용 종로 관광지
# pipeline: AI 백엔드 / 외부 데이터 (mock fallback)
# 구현(요약): 종로 관광지 7곳의 좌표·이름. service_key 없을 때 client가 사용.
#            실제 TourAPI 응답을 정규화한 노드 형태와 동일 스키마.
# 구현일: 2026-06-18 | 작성: kys (scenario-mvp/kys/v1)
# ============================================================

# (lat=mapY, lng=mapX) — 종로 대표 관광지. overview는 대화 grounding용(실데이터 detailCommon2 대체).
# density_tier는 비인기 task 전이라 비움.
MOCK_JONGNO_NODES = [
    {"node_id": "jongno_unhyeongung", "name": "운현궁", "map_y": 37.5745, "map_x": 126.9858,
     "overview": "운현궁은 흥선대원군 이하응의 사저로, 고종이 태어나 12세까지 자란 곳이다. 조선 말기 정치의 중심 무대였다."},
    {"node_id": "jongno_insadong", "name": "인사동", "map_y": 37.5740, "map_x": 126.9856,
     "overview": "인사동은 전통 공예품·고미술·화랑·찻집이 모인 거리로, 옛 한양의 문화 정취가 남아 있는 곳이다."},
    {"node_id": "jongno_gongye", "name": "서울공예박물관", "map_y": 37.5765, "map_x": 126.9800,
     "overview": "서울공예박물관은 옛 풍문여고 자리에 세운 국내 최초 공립 공예박물관으로, 전통과 현대 공예를 아우른다."},
    {"node_id": "jongno_gyeongbok", "name": "경복궁", "map_y": 37.5796, "map_x": 126.9770,
     "overview": "경복궁은 1395년 창건된 조선의 정궁으로, 광화문과 근정전을 중심으로 왕실의 위엄을 보여준다."},
    {"node_id": "jongno_ikseondong", "name": "익선동", "map_y": 37.5740, "map_x": 126.9905,
     "overview": "익선동은 1930년대 한옥이 보존된 골목으로, 좁은 길 사이 카페와 맛집이 어우러진 한옥 마을이다."},
    {"node_id": "jongno_changdeok", "name": "창덕궁", "map_y": 37.5794, "map_x": 126.9910,
     "overview": "창덕궁은 조선의 이궁으로 자연 지형을 살린 후원이 유명하며, 유네스코 세계문화유산으로 지정되었다."},
    {"node_id": "jongno_bukchon", "name": "북촌한옥마을", "map_y": 37.5826, "map_x": 126.9850,
     "overview": "북촌한옥마을은 경복궁과 창덕궁 사이 언덕에 자리한 전통 한옥 밀집지로, 조선 사대부의 주거 문화를 보여준다."},
]


def mock_nodes(region: str = "종로") -> list[dict]:
    """mock 노드 목록 반환. (현재 종로만 — 확장 시 region별 분기)"""
    return [dict(n, region=region, content_type_id=12, source="mock") for n in MOCK_JONGNO_NODES]
