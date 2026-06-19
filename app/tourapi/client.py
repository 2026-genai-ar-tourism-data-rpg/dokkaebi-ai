# ============================================================
# [v1] TourAPI KorService2 클라이언트 — 위치기반 관광정보 조회(거리순)
# pipeline: AI 백엔드 / 외부 데이터 (시나리오 생성의 노드 후보 fetch)
# 구현(요약): locationBasedList2(mapX,mapY,radius,arrange=E) → 노드 정규화.
#            공통 호출부(base.request) 사용. 키 없으면 mock 종로 노드(거리계산).
# 구현일: 2026-06-18 | 작성: kys (scenario-mvp/kys/v1)
# ============================================================
import json
import math

from app.config import get_settings
from app.core.cache import get_cache
from app.core.logger import get_logger
from app.tourapi.base import TourAPIError, request  # noqa: F401 (TourAPIError 재노출)
from app.tourapi.mock_nodes import mock_nodes

logger = get_logger(__name__)


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 간 직선거리(m). 거리순 정렬·반경 필터에 사용(임베딩 아님, 좌표 수학)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class TourAPIClient:
    """국문관광정보 TourAPI 래퍼. 거리순 위치기반 조회가 핵심(MVP).

    - location_based_list: 좌표+반경 내 관광지를 거리순으로. 키 없으면 mock.
    """

    def __init__(self) -> None:
        s = get_settings()
        self._base = s.tourapi_base_url.rstrip("/")
        self._key = s.tourapi_service_key

    async def location_based_list(
        self, map_x: float, map_y: float, radius_m: int,
        content_type_id: int = 12, rows: int = 30,
    ) -> list[dict]:
        """좌표(map_x=경도, map_y=위도) 반경 내 관광지를 **거리순**으로 반환.

        반환 노드: {node_id, name, map_x, map_y, content_type_id, dist_m, ...}
        키 없으면 mock 노드를 같은 형태로(거리계산·정렬) 반환.
        """
        if not self._key:
            logger.info("TourAPI 키 없음 → mock 종로 노드 사용")
            return self._mock_location_based(map_x, map_y, radius_m)

        result = await request(self._base, "locationBasedList2", {
            "numOfRows": rows,
            "mapX": map_x, "mapY": map_y, "radius": radius_m,
            "contentTypeId": content_type_id,
            "arrange": "E",  # E=거리순. TourAPI가 거리순 정렬을 보장
        })
        return self._to_nodes(result["items"])  # 이미 거리순

    async def search_keyword(
        self, keyword: str, content_type_id: int = 12, top_n: int = 10,
    ) -> list[dict]:
        """키워드로 관광지 검색 → 자동완성 후보 리스트. 앵커("꼭 가고싶은 곳") 해석용.

        ⚠️ 부분일치라 여러 개 나옴(예: '경복궁' → 경복궁 + 한복남 경복궁점).
        앱은 이 후보를 드롭다운으로 → 사용자가 탭. 정확 title 일치를 맨 앞으로 정렬.
        반환: [{node_id, tour_content_id, name, addr, map_x, map_y}]
        """
        if not self._key or not keyword:
            return []
        result = await request(self._base, "searchKeyword2", {
            "keyword": keyword, "contentTypeId": content_type_id, "numOfRows": top_n,
        })
        cands = []
        for it in result["items"]:
            cands.append({
                "node_id": f"tour_{it.get('contentid')}",
                "tour_content_id": it.get("contentid"),
                "name": it.get("title"),
                "addr": it.get("addr1"),
                "map_x": float(it["mapx"]) if it.get("mapx") else None,
                "map_y": float(it["mapy"]) if it.get("mapy") else None,
            })
        # 정확 일치(이름 == 키워드)를 맨 앞으로 — 지역코드 필터는 신뢰도 낮아 미사용
        cands.sort(key=lambda c: (c["name"] or "") != keyword)
        return cands

    async def detail_common(self, content_id: str) -> dict | None:
        """contentId의 공통 상세(overview 설명 텍스트 등). NPC 대화 grounding 원천.

        반환: {overview, homepage, tel} 또는 None. 캐시(persist-on-touch)로 재호출 0.
        키 없으면 None(mock은 노드에 overview 내장).
        """
        if not self._key or not content_id:
            return None
        # 캐시 우선(노드 상세는 거의 정적 → 긴 TTL). 두 번째부터 TourAPI 0콜
        cache, ckey = get_cache(), f"tourdetail:{content_id}"
        cached = await cache.get(ckey)
        if cached is not None:
            return json.loads(cached)

        result = await request(self._base, "detailCommon2", {
            "contentId": content_id, "numOfRows": 1,
        })
        items = result["items"]
        if not items:
            return None
        it = items[0]
        detail = {
            "overview": it.get("overview"),
            "homepage": it.get("homepage"),
            "tel": it.get("tel"),
        }
        await cache.set(ckey, json.dumps(detail, ensure_ascii=False), get_settings().tourapi_cache_ttl_s)
        return detail

    def _to_nodes(self, items: list[dict]) -> list[dict]:
        """locationBasedList2 item → 노드 정규화."""
        nodes = []
        for it in items:
            nodes.append({
                "node_id": f"tour_{it.get('contentid')}",
                "tour_content_id": it.get("contentid"),
                "name": it.get("title"),
                "map_x": float(it["mapx"]) if it.get("mapx") else None,
                "map_y": float(it["mapy"]) if it.get("mapy") else None,
                "content_type_id": int(it.get("contenttypeid", 0)),
                "addr1": it.get("addr1"), "addr2": it.get("addr2"),
                "dist_m": round(float(it["dist"]), 1) if it.get("dist") else None,
                "source": "TourAPI",
            })
        return nodes

    def _mock_location_based(self, map_x: float, map_y: float, radius_m: int) -> list[dict]:
        """mock 노드를 쿼리 좌표 기준 거리계산 → 반경 필터 → 거리순 정렬(실호출과 동일 형태)."""
        out = []
        for n in mock_nodes():
            d = haversine_m(map_y, map_x, n["map_y"], n["map_x"])
            if d <= radius_m:
                out.append({**n, "dist_m": round(d, 1)})
        out.sort(key=lambda x: x["dist_m"])
        return out
