# ============================================================
# [v1] 구글 priceLevel 커버리지 실측 — 채택/폐기 결정용 1회성 스크립트
# 목적: "종로 식당 중 구글이 가격대(₩~₩₩₩₩)를 아는 비율"을 숫자로 확인.
#       이 숫자를 보고 구글 priceLevel 방식을 채택할지 폐기할지 결정한다.
#       (커버리지도 모르고 본코드부터 짜는 실수 방지 — 실측 먼저)
#
# 사용법: 레포 루트 .env에 키를 넣고 실행 (팀 컨벤션 — config.py와 동일한 .env 사용)
#   DOKKAEBI_GOOGLE_MAPS_API_KEY=...   # 필수 (billing 켜고 콘솔 일일 상한 걸어둘 것!)
#   DOKKAEBI_TOURAPI_SERVICE_KEY=...   # 선택 (있으면 A모드=정확한 측정)
#   python scripts/measure_price_coverage.py [--limit 30]
#   (셸 export도 여전히 동작 — .env가 없을 때의 폴백)
#
# 두 가지 모드:
#   A (TourAPI 키 있음, 권장): TourAPI 39로 "우리 실제 후보 풀"을 뽑고, 각 후보를
#     구글 Text Search로 찾아 priceLevel 유무 확인 → "우리 후보 중 몇 %" (정확한 지표)
#   B (TourAPI 키 없음): 구글 Nearby로 안국역 주변 식당을 받아 priceLevel 유무 확인
#     → 구글이 아는 가게 기준이라 실제보다 후하게 나올 수 있음(편향 주의)
#
# 비용: --limit 30 기준 Text Search 30콜 안팎 = Pro 무료상한(월 5,000) 내, 실질 $0.
# 판정 가이드(팀 합의로 조정): 보유율 >= 50% → 채택 검토 / < 50% → 폐기하고 참가격 방식으로.
# 구현일: 2026-07-04 | 작성: pjh (food-budget/pjh/v1)
# ============================================================
import argparse
import asyncio
import os
import sys

import httpx

# 팀 config를 통해 .env 로드 (레포 루트에서 실행 기준). 스크립트 단독 실행도 지원.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import get_settings  # noqa: E402

ANGUK = {"lat": 37.5766, "lng": 126.9854}   # 안국역 (MVP 시나리오 시작점)
RADIUS_M = 800
GOOGLE_TEXT = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_NEARBY = "https://places.googleapis.com/v1/places:searchNearby"
FIELDS = "places.id,places.displayName,places.priceLevel"

# 구글 priceLevel enum → 표시용
LEVEL_LABEL = {
    "PRICE_LEVEL_INEXPENSIVE": "₩",
    "PRICE_LEVEL_MODERATE": "₩₩",
    "PRICE_LEVEL_EXPENSIVE": "₩₩₩",
    "PRICE_LEVEL_VERY_EXPENSIVE": "₩₩₩₩",
    "PRICE_LEVEL_FREE": "무료",
}


async def fetch_tourapi_candidates(limit: int) -> list[dict]:
    """A모드: TourAPI 39로 우리 실제 후보 풀(종로 식당) 추출."""
    s = get_settings()
    key = s.tourapi_service_key
    url = f"{s.tourapi_base_url}/locationBasedList2"
    params = {
        "serviceKey": key, "MobileOS": "ETC", "MobileApp": "coverage-check",
        "_type": "json", "numOfRows": limit, "pageNo": 1,
        "mapX": ANGUK["lng"], "mapY": ANGUK["lat"], "radius": RADIUS_M,
        "contentTypeId": 39, "arrange": "E",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, params=params)
    r.raise_for_status()
    items = (r.json().get("response", {}).get("body", {})
             .get("items", {}) or {}).get("item", [])
    if isinstance(items, dict):
        items = [items]
    return [{"name": it.get("title"), "lat": float(it["mapy"]), "lng": float(it["mapx"])}
            for it in items if it.get("mapy")]


async def google_text_search(client: httpx.AsyncClient, api_key: str, cand: dict) -> str | None:
    """후보 1곳을 이름+좌표로 구글에서 찾아 priceLevel 반환(없으면 None)."""
    body = {
        "textQuery": cand["name"], "languageCode": "ko",
        "locationBias": {"circle": {"center": {"latitude": cand["lat"], "longitude": cand["lng"]},
                                     "radius": 200.0}},
        "maxResultCount": 1,
    }
    r = await client.post(GOOGLE_TEXT, json=body, headers={
        "X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELDS})
    r.raise_for_status()
    places = r.json().get("places", [])
    if not places:
        return "NOT_FOUND"           # 구글에 가게 자체가 없음
    return places[0].get("priceLevel")  # 있으면 enum, 필드 없으면 None


async def google_nearby(client: httpx.AsyncClient, api_key: str, limit: int) -> list[dict]:
    """B모드: 구글 Nearby로 안국역 주변 식당 직접 수집(편향 주의 — 헤더 출력에 명시)."""
    body = {
        "includedTypes": ["restaurant", "cafe"], "maxResultCount": min(limit, 20),
        "locationRestriction": {"circle": {
            "center": {"latitude": ANGUK["lat"], "longitude": ANGUK["lng"]},
            "radius": float(RADIUS_M)}},
        "languageCode": "ko",
    }
    r = await client.post(GOOGLE_NEARBY, json=body, headers={
        "X-Goog-Api-Key": api_key, "X-Goog-FieldMask": FIELDS})
    r.raise_for_status()
    return r.json().get("places", [])


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=30, help="확인할 후보 수 (기본 30 — 무료 범위)")
    args = ap.parse_args()

    s = get_settings()   # .env(DOKKAEBI_*) 자동 로드 — config.py와 동일 경로
    api_key = getattr(s, "google_maps_api_key", "") or os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        sys.exit(".env에 DOKKAEBI_GOOGLE_MAPS_API_KEY가 없습니다. 키 발급 후 다시 실행하세요.\n"
                 "(발급: Google Cloud Console → Places API(New) 활성화 → billing 연결 → "
                 "⚠️ 할당량에서 일일 요청 상한부터 설정!)")

    tourapi_mode = bool(s.tourapi_service_key)
    counts: dict[str, int] = {}
    rows: list[tuple[str, str]] = []

    async with httpx.AsyncClient(timeout=15) as client:
        if tourapi_mode:
            print(f"[A모드] TourAPI 39 실제 후보 풀 기준 측정 (정확한 지표)")
            cands = await fetch_tourapi_candidates(args.limit)
            if not cands:
                sys.exit("TourAPI 후보 0건 — 키/파라미터 확인 필요")
            for c in cands:
                level = await google_text_search(client, api_key, c)
                label = LEVEL_LABEL.get(level, "없음" if level is None else level)
                rows.append((c["name"], label))
                counts[label] = counts.get(label, 0) + 1
                await asyncio.sleep(0.2)   # 예의상 간격 (rate limit 여유)
        else:
            print(f"[B모드] 구글 Nearby 기준 측정 — ⚠️ 구글이 아는 가게만 모수라서 "
                  f"실제 후보 풀 대비 후하게 나올 수 있음. TourAPI 키 넣고 A모드 권장.")
            places = await google_nearby(client, api_key, args.limit)
            for p in places:
                name = (p.get("displayName") or {}).get("text", "?")
                level = p.get("priceLevel")
                label = LEVEL_LABEL.get(level, "없음" if level is None else level)
                rows.append((name, label))
                counts[label] = counts.get(label, 0) + 1

    total = len(rows)
    have = sum(v for k, v in counts.items() if k.startswith("₩"))
    print(f"\n{'가게':<28}priceLevel")
    print("-" * 42)
    for name, label in rows:
        print(f"{name:<28}{label}")
    print("-" * 42)
    print(f"총 {total}곳 / priceLevel 보유 {have}곳 = 보유율 {have/total*100:.0f}%")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}곳")
    print(f"\n판정 가이드: 보유율 50% 이상이면 구글 방식 채택 검토, "
          f"미만이면 폐기하고 참가격(한식/중식 카테고리 평균) 방식으로.")


if __name__ == "__main__":
    asyncio.run(main())
