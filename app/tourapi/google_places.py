# ============================================================
# [v1] Google Places 접근층 — 업소별 가격대(priceLevel, ₩~₩₩₩₩) 조회
# pipeline: AI 백엔드 / 외부 데이터 (food.py 예산 밴드 매칭이 소비)
# 구현(요약): "외부 소스 1개 = 파일 1개" 컨벤션(bigdata.py와 동일).
#   · Text Search(New)로 이름+좌표 매칭 → priceLevel(1~4 밴드) 반환
#   · 업소 가격대는 거의 안 변함 → app.core.cache 7일 TTL (tourapi overview와 동일 패턴)
#   · 키 없으면 None 반환(호출 안 함) — food.py가 mock/미상 처리
#   · 실패해도 시나리오 생성을 절대 막지 않음 (가격대 미상으로 폴백)
# ⚠️ 채택 조건부: scripts/measure_price_coverage.py로 종로 보유율 실측 후
#    50% 미만이면 이 방식 폐기 예정 (HANDOFF §6). 비용: Pro 무료상한(월 5천콜) 내
#    파일럿 무료 — 단 billing 연결·일일 상한 설정은 사람이 해야 함.
# 구현일: 2026-07-04 | 작성: pjh (food-budget/pjh/v1)
# ============================================================
import asyncio

import httpx

from app.config import get_settings
from app.core.cache import get_cache
from app.core.logger import get_logger

logger = get_logger(__name__)

_TEXT_SEARCH = "https://places.googleapis.com/v1/places:searchText"
_FIELDS = "places.id,places.priceLevel"

# 구글 priceLevel enum → 밴드 정수(1=₩ ... 4=₩₩₩₩). 미상/무료는 None(미상 취급).
_LEVEL_TO_BAND = {
    "PRICE_LEVEL_INEXPENSIVE": 1,
    "PRICE_LEVEL_MODERATE": 2,
    "PRICE_LEVEL_EXPENSIVE": 3,
    "PRICE_LEVEL_VERY_EXPENSIVE": 4,
}

BAND_LABEL = {1: "₩", 2: "₩₩", 3: "₩₩₩", 4: "₩₩₩₩", None: "가격대 정보 없음"}


async def fetch_price_band(name: str, lat: float, lng: float) -> int | None:
    """업소 1곳의 가격대 밴드(1~4) 조회. 키 없음/미발견/실패 = None(미상).

    캐시 키는 이름+좌표(구글 place_id를 아직 모르는 시점이라) — hit이면 호출 0.
    """
    s = get_settings()
    api_key = getattr(s, "google_maps_api_key", "")
    if not api_key:
        return None                      # 키 없음 — 호출 자체를 안 함 (mock 경로는 food.py)

    cache = get_cache()
    cache_key = f"gprice:{name}:{round(lat,4)}:{round(lng,4)}"
    cached = await cache.get(cache_key)
    if cached is not None:
        return None if cached == "none" else int(cached)

    try:
        body = {
            "textQuery": name, "languageCode": "ko", "maxResultCount": 1,
            "locationBias": {"circle": {
                "center": {"latitude": lat, "longitude": lng}, "radius": 200.0}},
        }
        timeout = getattr(s, "google_places_timeout", 10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(_TEXT_SEARCH, json=body, headers={
                "X-Goog-Api-Key": api_key, "X-Goog-FieldMask": _FIELDS})
        r.raise_for_status()
        places = r.json().get("places", [])
        band = _LEVEL_TO_BAND.get(places[0].get("priceLevel")) if places else None
    except Exception as e:               # 가격대는 부가정보 — 실패=미상, 경로는 계속
        logger.warning("priceLevel 조회 실패(%s) → 미상 처리: %s", name, e)
        band = None

    ttl = getattr(s, "google_price_cache_ttl_s", 604800)
    await cache.set(cache_key, "none" if band is None else str(band), ttl)
    return band


async def attach_price_bands(cands: list[dict]) -> list[dict]:
    """후보 리스트에 price_band/price_band_label/price_source 부착 (동시 조회, 세마포어)."""
    s = get_settings()
    sem = asyncio.Semaphore(getattr(s, "google_places_semaphore", 5))

    async def _one(c: dict) -> None:
        async with sem:
            band = await fetch_price_band(c["name"], c["map_y"], c["map_x"])
        c["price_band"] = band
        c["price_band_label"] = BAND_LABEL[band]
        c["price_source"] = "google" if band is not None else None

    await asyncio.gather(*(_one(c) for c in cands))
    return cands