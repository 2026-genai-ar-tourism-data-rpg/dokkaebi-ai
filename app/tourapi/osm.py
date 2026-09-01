# ============================================================
# [v1] OSM 접근층 — 키리스 실데이터 (TourAPI 키 없을 때의 POI·검색 원천)
# pipeline: AI 백엔드 / 외부 데이터 (client.py 폴백이 소비)
# 구현(요약): "외부 소스 1개 = 파일 1개" 컨벤션(google_places.py와 동일).
#   · Overpass: 반경 내 tourism/historic/leisure POI → TourAPI 노드 스키마로 정규화
#   · Nominatim: 키워드 → 검색 후보(앵커 선택용). KR 한정, 한국어 라벨
#   · 둘 다 공개 인스턴스 정책 준수: User-Agent 필수, 캐시로 재호출 최소화
#     (Nominatim 1req/s 제한 — 앱 디바운스 400ms만으론 초과 가능해 캐시가 방어)
#   · OSM엔 overview(설명문)가 없음 → 대사 grounding은 이름·주소만으로(генератор가 허용)
#   · 실측(2026-09-01): 관악구 좌표 반경 2000m에서 POI 60개 — 종로 밖에서도 코스 성립
# 구현일: 2026-09-01 | 작성: 정찬희
# ============================================================
import asyncio
import hashlib
import json
import math

import httpx

from app.config import get_settings
from app.core.cache import get_cache
from app.core.logger import get_logger

logger = get_logger(__name__)

# Overpass 태그 필터 — 이름 있는 관광성 POI만.
# leisure는 park/garden만(어린이공원 등 소형도 포함되지만 거리순이라 자연 후순위).
_OVERPASS_QUERY = """
[out:json][timeout:{timeout}];
(
  nwr["tourism"~"attraction|museum|gallery|viewpoint|zoo|theme_park|artwork|aquarium"]["name"](around:{radius},{lat},{lon});
  nwr["historic"]["name"](around:{radius},{lat},{lon});
  nwr["leisure"~"^(park|garden)$"]["name"](around:{radius},{lat},{lon});
);
out center {cap};
"""

# Overpass 전멸 시 폴백으로 훑을 Nominatim 특수 카테고리(위 태그 필터와 대응).
_NOMINATIM_CATEGORIES = ["attraction", "museum", "park", "memorial", "artwork", "viewpoint"]
_NOMINATIM_MIN_INTERVAL_S = 1.1  # 공개 인스턴스 1req/s 정책

# OSM 태그 → 앱이 아이콘·필터로 쓰는 카테고리. 앱 NearbyCategory와 문자열이 일치해야 한다.
# 태그 종류가 수십 개라 그대로 넘기면 앱이 분기 지옥이 된다 → 여기서 6종으로 좁힌다.
_CATEGORY_OF_TOURISM = {
    "museum": "museum", "gallery": "museum", "aquarium": "museum",
    "artwork": "artwork",
    "viewpoint": "viewpoint",
    "attraction": "attraction", "zoo": "attraction", "theme_park": "attraction",
}


def _category_of(tags: dict) -> str:
    """OSM 태그에서 카테고리 1개를 고른다. 우선순위: 유적 > 관광 태그 > 공원 > 기타.

    historic을 최우선으로 두는 이유 — 도깨비 설화와 가장 잘 붙는 자리이고,
    historic + tourism이 함께 붙은 노드(예: 유적이면서 명소)를 '명소'로 뭉개면
    목록에서 유적만 골라 보는 필터가 무의미해진다.
    """
    if tags.get("historic"):
        return "historic"
    tourism = tags.get("tourism")
    if tourism in _CATEGORY_OF_TOURISM:
        return _CATEGORY_OF_TOURISM[tourism]
    if tags.get("leisure") in ("park", "garden"):
        return "park"
    return "other"


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """두 좌표 간 직선거리(m). client.haversine_m과 동일 공식 — 순환 import 회피용 사본."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


async def location_based(
    map_x: float, map_y: float, radius_m: int, rows: int = 30,
) -> list[dict]:
    """좌표(map_x=경도, map_y=위도) 반경 내 OSM POI를 거리순으로 — TourAPI 노드 스키마.

    반환 노드: {node_id, name, map_x, map_y, content_type_id, dist_m, addr1, source}
    같은 이름의 중복(way+node 이중 등록)은 가까운 쪽 1개만 남긴다.
    """
    s = get_settings()
    cache = get_cache()
    ckey = f"osmpoi:{round(map_y, 4)}:{round(map_x, 4)}:{radius_m}"
    cached = await cache.get(ckey)
    if cached is not None:
        return json.loads(cached)

    query = _OVERPASS_QUERY.format(
        timeout=int(s.osm_timeout), radius=radius_m, lat=map_y, lon=map_x,
        cap=max(rows * 3, 60),  # 중복 제거·이름 결측 감안해 넉넉히 받는다
    )
    # 공개 인스턴스는 과부하 504가 잦다 → 목록 순서대로 페일오버.
    # 전부 실패해도 예외를 올리지 않는다: Nominatim 폴백으로 내려가 코스는 만들어진다
    # (2026-09-01 미러 3개 동시 다운으로 시나리오 생성이 500으로 막힌 적 있음).
    urls = [u.strip() for u in s.osm_overpass_urls.split(",") if u.strip()]
    elements: list[dict] = []
    async with httpx.AsyncClient(timeout=s.osm_timeout) as client:
        for url in urls:
            try:
                r = await client.post(
                    url, data={"data": query},
                    headers={"User-Agent": s.osm_user_agent},
                )
                r.raise_for_status()
                elements = r.json().get("elements", [])
            except (httpx.HTTPStatusError, httpx.TransportError, ValueError) as e:
                logger.warning("Overpass 인스턴스 실패(%s) → 다음 미러: %s", url, e)
                continue
            # ⚠️ 200이어도 빈 결과면 실패로 본다 — 지역 전용 미러(예: overpass.osm.ch는
            # 스위스 DB)가 한국 쿼리에 200 + elements:[] 를 준다. 이걸 성공으로 받으면
            # 조용히 "관광지 없음"이 되어 원인 추적이 어렵다.
            if elements:
                break
            logger.warning("Overpass 응답 비어 있음(%s) → 지역 전용 미러 의심, 다음으로", url)
    if not elements:
        logger.warning("Overpass 미러 전부 실패/빈 결과 → Nominatim 폴백")
        nodes = await _nominatim_area_pois(map_x, map_y, radius_m, rows)
        if nodes:
            await cache.set(ckey, json.dumps(nodes, ensure_ascii=False), s.osm_cache_ttl_s)
        return nodes

    seen_names: dict[str, dict] = {}
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if not name or lat is None or lon is None:
            continue
        node = {
            "node_id": f"osm_{el['type']}{el['id']}",
            "tour_content_id": None,  # TourAPI 아님 — detailCommon2 조회 불가
            "name": name,
            "map_x": float(lon), "map_y": float(lat),
            "content_type_id": 12,  # 관광지 컨벤션 유지(생성기 필터 호환)
            "category": _category_of(tags),
            "addr1": tags.get("addr:full") or tags.get("addr:street"),
            "addr2": None,
            "dist_m": round(_haversine_m(map_y, map_x, lat, lon), 1),
            "source": "OSM",
        }
        prev = seen_names.get(name)
        if prev is None or node["dist_m"] < prev["dist_m"]:
            seen_names[name] = node

    nodes = sorted(seen_names.values(), key=lambda n: n["dist_m"])[:rows]
    await cache.set(ckey, json.dumps(nodes, ensure_ascii=False), s.osm_cache_ttl_s)
    logger.info("OSM POI %d개 (반경 %dm, 좌표 %.4f,%.4f)", len(nodes), radius_m, map_y, map_x)
    return nodes


async def _nominatim_area_pois(
    map_x: float, map_y: float, radius_m: int, rows: int,
) -> list[dict]:
    """Overpass 미러가 전부 죽었을 때의 최종 폴백 — Nominatim 카테고리 검색.

    Overpass보다 결과 수가 훨씬 적지만(수십 → 수 개), 코스가 아예 안 만들어지는 것보다 낫다.
    Nominatim은 1req/s 정책이라 카테고리를 순차 호출하고 사이에 간격을 둔다.
    """
    s = get_settings()
    # 반경 → bbox. 위도 1도 ≈ 111.32km, 경도 1도 ≈ 111.32km * cos(lat).
    dlat = radius_m / 111320.0
    dlon = radius_m / (111320.0 * max(math.cos(math.radians(map_y)), 0.01))
    viewbox = f"{map_x - dlon},{map_y + dlat},{map_x + dlon},{map_y - dlat}"

    seen: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=s.osm_timeout) as client:
        for i, category in enumerate(_NOMINATIM_CATEGORIES):
            if i:
                await asyncio.sleep(_NOMINATIM_MIN_INTERVAL_S)  # 1req/s 정책
            try:
                r = await client.get(
                    s.osm_nominatim_url,
                    params={
                        "q": f"[{category}]", "format": "jsonv2",
                        "viewbox": viewbox, "bounded": 1,
                        "limit": rows, "accept-language": "ko",
                    },
                    headers={"User-Agent": s.osm_user_agent},
                )
                r.raise_for_status()
                items = r.json()
            except (httpx.HTTPStatusError, httpx.TransportError, ValueError) as e:
                logger.warning("Nominatim 카테고리(%s) 조회 실패: %s", category, e)
                continue

            for it in items:
                name = it.get("name")
                if not name or not it.get("lat") or not it.get("lon"):
                    continue
                lat, lon = float(it["lat"]), float(it["lon"])
                dist = _haversine_m(map_y, map_x, lat, lon)
                if dist > radius_m:
                    continue  # bounded=1이 bbox 기준이라 모서리가 반경을 넘는다
                node = {
                    "node_id": f"osm_{it.get('osm_type', 'x')}{it.get('osm_id', it.get('place_id'))}",
                    "tour_content_id": None,
                    "name": name,
                    "map_x": lon, "map_y": lat,
                    "content_type_id": 12,
                    # 폴백은 태그가 없다 — 어느 카테고리로 질의해 나온 결과인지가 곧 분류다.
                    "category": "historic" if category == "memorial" else category,
                    "addr1": it.get("display_name"),
                    "addr2": None,
                    "dist_m": round(dist, 1),
                    "source": "OSM-Nominatim",
                }
                prev = seen.get(name)
                if prev is None or node["dist_m"] < prev["dist_m"]:
                    seen[name] = node

    nodes = sorted(seen.values(), key=lambda n: n["dist_m"])[:rows]
    logger.info("Nominatim 폴백 POI %d개 (반경 %dm)", len(nodes), radius_m)
    return nodes


async def search_keyword(keyword: str, top_n: int = 10) -> list[dict]:
    """Nominatim 키워드 검색 → 검색 후보(TourAPI searchKeyword2와 동일 스키마).

    반환: [{node_id, tour_content_id, name, addr, map_x, map_y}]
    KR 한정. 캐시 필수(1req/s 정책) — 같은 키워드 재검색은 호출 0.
    """
    s = get_settings()
    cache = get_cache()
    ckey = "osmsearch:" + hashlib.md5(keyword.encode()).hexdigest()
    cached = await cache.get(ckey)
    if cached is not None:
        return json.loads(cached)

    async with httpx.AsyncClient(timeout=s.osm_timeout) as client:
        r = await client.get(
            s.osm_nominatim_url,
            params={
                "q": keyword, "format": "jsonv2", "countrycodes": "kr",
                "limit": top_n, "accept-language": "ko",
            },
            headers={"User-Agent": s.osm_user_agent},
        )
    r.raise_for_status()

    cands = []
    for it in r.json():
        osm_id = f"osm_{it.get('osm_type', 'x')}{it.get('osm_id', it.get('place_id'))}"
        cands.append({
            "node_id": osm_id,
            # 위시 앵커 매칭 키 — OSM 후보로 만든 위시는 OSM 시나리오 안에서만 쓰이므로
            # node_id를 그대로 content_id로 재사용(좌표·이름이 함께 가서 합성 앵커도 성립).
            "tour_content_id": osm_id,
            "name": it.get("name") or (it.get("display_name", "").split(",")[0]),
            "addr": it.get("display_name"),
            "map_x": float(it["lon"]) if it.get("lon") else None,
            "map_y": float(it["lat"]) if it.get("lat") else None,
        })
    # 정확 일치를 맨 앞으로(client.search_keyword와 동일 규칙)
    cands.sort(key=lambda c: (c["name"] or "") != keyword)
    await cache.set(ckey, json.dumps(cands, ensure_ascii=False), s.osm_cache_ttl_s)
    return cands
