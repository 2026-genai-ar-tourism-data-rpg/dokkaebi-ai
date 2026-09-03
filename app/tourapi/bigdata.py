# ============================================================
# [v1] TourAPI 빅데이터 계열 클라이언트 — 연관·집중률·중심·방문자수
# pipeline: AI 백엔드 / 외부 데이터 (비인기 라벨링·연관 동선 task의 데이터 접근층)
# 구현(요약): 4개 서비스 호출 로직. 공통 호출부(base.request_all) 위에 서비스별 메서드.
#            ⚠️ 데이터 '사용'(비인기 컷오프·연관 동선)은 별도 task(박준형 EDA). 여기는 '접근'만.
#            ⚠️ 빅데이터 코드(tAtsCd 등)는 KorService2 contentId와 다름 → 매칭 별도.
# 구현일: 2026-06-18 | 작성: kys (bigdata-client/kys/v1)
# 참고: report/외부API 빅데이터 정리 문서
# ============================================================
# [v2 추가] 비인기 앵커 선택용 동기 helper — density.py 전용
# - generator.py 수정 금지 조건 때문에 build_route(sync) 경로에서 호출 가능해야 함.
#   (실행 중인 이벤트 루프 안이라 asyncio.run() 불가 → httpx.Client 동기 호출)
# - 기본은 지역 벌크 조회 + TTL 캐시, 개별 tAtsNm 조회는 제한 fallback용.
# - 원본 API key는 정규화하지 않고 그대로 반환함.
# 구현일: 2026-07-04 | 작성: ljs (lowtraffic-select/ljs/v1)
# ------------------------------------------------------------
# [v3] 동기 호출이 이벤트 루프를 막던 문제 해소(호출측) + 중복 fetch 방지.
# 구현(요약): v2 주석의 전제("루프 안이라 asyncio.run 불가")가 실제로는 루프 블로킹이었다.
#            비인기 앵커를 켜면 이 동기 httpx가 최대 40페이지 도는 동안 FastAPI 워커
#            전체가 멈춰 다른 사용자의 요청까지 대기했다.
#            → generator가 build_route를 asyncio.to_thread로 넘겨 루프를 비운다(호출측 수정).
#              여기서는 그로 인해 가능해진 동시 캐시 미스를 락으로 직렬화해, 같은 지역을
#              여러 스레드가 중복 fetch하지 않게 한다.
#            네트워크 예외는 base.network_error로 통일(재시도 가능 장애로 분류).
# 구현일: 2026-08-12 | 작성: pjh (ai-logic-fix/pjh/v2)
# ============================================================
from __future__ import annotations

import threading
import time
from datetime import date
from typing import Any

import httpx

from app.config import get_settings
from app.core.logger import get_logger
from app.tourapi.base import TourAPIError, network_error, request_all

logger = get_logger(__name__)

_OK_CODES = ("0000", "00", "0")
_DENSITY_SNAPSHOT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_DENSITY_TATS_NAME_CACHE: dict[str, tuple[float, list[dict]]] = {}
# snapshot 조회는 최대 40페이지짜리 동기 호출이다. generator가 build_route를 to_thread로
# 넘기면서 여러 요청이 동시에 캐시 미스를 맞을 수 있어, 같은 지역 중복 fetch를 막는다.
# (지역 수가 적어 지역별 락 대신 단일 락 — 다른 지역은 잠깐 직렬화된다)
_DENSITY_SNAPSHOT_LOCK = threading.Lock()


def recent_base_ym(months_ago: int = 2) -> str:
    """기준 연월(YYYYMM) 헬퍼. 빅데이터는 월단위 갱신·지연 → 기본 2개월 전.

    (가용 최신월은 서비스마다 다름 → 빈 결과면 months_ago를 늘려 재시도)
    """
    today = date.today()
    m = today.month - months_ago
    y = today.year
    while m <= 0:
        m += 12
        y -= 1
    return f"{y}{m:02d}"


class BigDataTourClient:
    """B551011 빅데이터 4종 서비스 클라이언트. 전부 페이지네이션(request_all)으로 전체 수집.

    - 연관 관광지(TarRlteTarService1): related_by_area / related_by_keyword
    - 집중률(TatsCnctrRateService):     concentration_rate
    - 중심 관광지(LocgoHubTarService1): hub_attractions
    - 방문자수(DataLabService):         metco_visitors(광역) / locgo_visitors(기초)
    """

    def __init__(self) -> None:
        self._root = get_settings().tourapi_data_base_url.rstrip("/")

    # --- 1. 관광지별 연관 관광지 (함께 방문되는 곳 → 시나리오 동선 후보) ---
    async def related_by_area(self, area_cd: str, signgu_cd: str, base_ym: str, rows: int = 100) -> list[dict]:
        """시군구 내 관광지별 연관 관광지 목록(기준+연관 코드, rank)."""
        return await request_all(f"{self._root}/TarRlteTarService1", "areaBasedList1", {
            "baseYm": base_ym, "areaCd": area_cd, "signguCd": signgu_cd, "numOfRows": rows,
        })

    async def related_by_keyword(self, keyword: str, base_ym: str, rows: int = 100) -> list[dict]:
        """관광지명 키워드 기준 연관 관광지 목록."""
        return await request_all(f"{self._root}/TarRlteTarService1", "searchKeyword1", {
            "baseYm": base_ym, "keyword": keyword, "numOfRows": rows,
        })

    # --- 2. 관광지별 집중률 (향후 30일 혼잡 예측 → 비인기/한산도) ---
    async def concentration_rate(self, area_cd: str, signgu_cd: str,
                                 t_ats_nm: str | None = None, rows: int = 100) -> list[dict]:
        """시군구 관광지 집중률(조회일 기준 향후 30일, cnctrRate). 관광지명으로 필터 가능."""
        params = {"areaCd": area_cd, "signguCd": signgu_cd, "numOfRows": rows}
        if t_ats_nm:
            params["tAtsNm"] = t_ats_nm
        return await request_all(f"{self._root}/TatsCnctrRateService", "tatsCnctrRatedList", params)

    # --- 3. 기초지자체 중심 관광지 (중심성 랭킹 → 인기/앵커 vs 비인기/샛길) ---
    async def hub_attractions(self, area_cd: str, signgu_cd: str, base_ym: str, rows: int = 100) -> list[dict]:
        """시군구 내 중심성 높은 관광지 랭킹(hubTatsCd, rank)."""
        return await request_all(f"{self._root}/LocgoHubTarService1", "areaBasedList1", {
            "baseYm": base_ym, "areaCd": area_cd, "signguCd": signgu_cd, "numOfRows": rows,
        })

    # --- 4. 관광빅데이터 방문자수 (지역 단위 트렌드/EDA) ---
    async def metco_visitors(self, start_ymd: str, end_ymd: str,
                             area_code: str | None = None, rows: int = 100) -> list[dict]:
        """광역지자체 일별 방문자수(touNum). 코드 파라미터명 주의: areaCode(Cd 아님)."""
        params = {"startYmd": start_ymd, "endYmd": end_ymd, "numOfRows": rows}
        if area_code:
            params["areaCode"] = area_code
        return await request_all(f"{self._root}/DataLabService", "metcoRegnVisitrDDList", params)

    async def locgo_visitors(self, start_ymd: str, end_ymd: str,
                             area_code: str, signgu_code: str, rows: int = 100) -> list[dict]:
        """기초지자체 일별 방문자수. 코드 파라미터명: areaCode / signguCode."""
        return await request_all(f"{self._root}/DataLabService", "locgoRegnVisitrDDList", {
            "startYmd": start_ymd, "endYmd": end_ymd,
            "areaCode": area_code, "signguCode": signgu_code, "numOfRows": rows,
        })


# -----------------------------------------------------------------------------
# 비인기 앵커 선택용 동기 helper
# -----------------------------------------------------------------------------


def get_density_region_codes(region: str | None = None) -> tuple[str, str] | None:
    """지역명 → BigData API areaCd/signguCd. MVP 기본 지역은 config.density_default_region."""
    s = get_settings()
    target = region or s.density_default_region
    codes = s.density_region_code_map.get(target)
    if not codes:
        logger.warning("비인기 앵커 지역 코드 없음: %s", target)
        return None
    area_cd = codes.get("areaCd")
    signgu_cd = codes.get("signguCd")
    if not area_cd or not signgu_cd:
        logger.warning("비인기 앵커 지역 코드 불완전: %s=%s", target, codes)
        return None
    return area_cd, signgu_cd


def fetch_density_snapshot_sync(region: str | None = None) -> dict[str, Any] | None:
    """지역 단위 BigData snapshot 조회.

    반환 원칙:
      - concentration_rows: TatsCnctrRateService 원본 row 리스트
      - hub_rows: LocgoHubTarService1 원본 row 리스트
      - areaCd/signguCd/baseYm/region: 매칭·캐시용 메타

    실패 시 None을 반환해 호출측이 `return []` 정책을 적용하도록 한다.
    """
    s = get_settings()
    target_region = region or s.density_default_region
    codes = get_density_region_codes(target_region)
    if not codes:
        return None

    area_cd, signgu_cd = codes
    base_ym = recent_base_ym(s.density_hub_base_months_ago)
    cache_key = f"density:snapshot:{target_region}:{area_cd}:{signgu_cd}:{base_ym}"
    cached = _cache_get(_DENSITY_SNAPSHOT_CACHE, cache_key)
    if cached is not None:
        return cached

    with _DENSITY_SNAPSHOT_LOCK:
        # 락을 기다리는 동안 다른 스레드가 채웠을 수 있다(double-check) → 중복 fetch 회피
        cached = _cache_get(_DENSITY_SNAPSHOT_CACHE, cache_key)
        if cached is not None:
            return cached
        return _fetch_density_snapshot(s, target_region, area_cd, signgu_cd, base_ym, cache_key)


def _fetch_density_snapshot(
    s: Any, target_region: str, area_cd: str, signgu_cd: str, base_ym: str, cache_key: str,
) -> dict[str, Any] | None:
    """snapshot 실제 조회 + 캐시 적재. 호출측이 락과 캐시 확인을 마친 뒤 부른다."""
    root = s.tourapi_data_base_url.rstrip("/")
    try:
        concentration_rows = _sync_request_all(
            f"{root}/TatsCnctrRateService",
            "tatsCnctrRatedList",
            {
                "areaCd": area_cd,
                "signguCd": signgu_cd,
                "numOfRows": s.density_cnctr_num_of_rows,
            },
            max_pages=s.density_cnctr_max_pages,
        )
        hub_rows = _sync_request_all(
            f"{root}/LocgoHubTarService1",
            "areaBasedList1",
            {
                "baseYm": base_ym,
                "areaCd": area_cd,
                "signguCd": signgu_cd,
                "numOfRows": s.density_hub_num_of_rows,
            },
            max_pages=s.density_hub_max_pages,
        )
    except Exception as e:
        logger.warning("비인기 앵커 BigData snapshot 조회 실패(%s): %s", target_region, e)
        return None

    snapshot = {
        "region": target_region,
        "areaCd": area_cd,
        "signguCd": signgu_cd,
        "baseYm": base_ym,
        "concentration_rows": concentration_rows,
        "hub_rows": hub_rows,
    }
    _cache_set(_DENSITY_SNAPSHOT_CACHE, cache_key, snapshot, s.density_bigdata_cache_ttl_s)
    return snapshot


def fetch_concentration_by_name_sync(area_cd: str, signgu_cd: str, t_ats_nm: str) -> list[dict]:
    """벌크 매칭 실패 시 제한적으로 사용하는 관광지명별 집중률 조회.

    결과는 관광지명 단위로 TTL 캐시하여 같은 장소 재조회 비용을 줄인다.
    """
    s = get_settings()
    name = (t_ats_nm or "").strip()
    if not name:
        return []

    cache_key = f"density:tats:{area_cd}:{signgu_cd}:{name}"
    cached = _cache_get(_DENSITY_TATS_NAME_CACHE, cache_key)
    if cached is not None:
        return cached

    root = s.tourapi_data_base_url.rstrip("/")
    try:
        rows = _sync_request_all(
            f"{root}/TatsCnctrRateService",
            "tatsCnctrRatedList",
            {
                "areaCd": area_cd,
                "signguCd": signgu_cd,
                "tAtsNm": name,
                "numOfRows": s.density_targeted_num_of_rows,
            },
            max_pages=s.density_cnctr_max_pages,
        )
    except Exception as e:
        logger.warning("관광지명 집중률 조회 실패(%s): %s", name, e)
        rows = []

    _cache_set(_DENSITY_TATS_NAME_CACHE, cache_key, rows, s.density_bigdata_cache_ttl_s)
    return rows


def _cache_get(cache: dict[str, tuple[float, Any]], key: str) -> Any | None:
    item = cache.get(key)
    if not item:
        return None
    expires_at, value = item
    if time.time() >= expires_at:
        cache.pop(key, None)
        return None
    return value


def _cache_set(cache: dict[str, tuple[float, Any]], key: str, value: Any, ttl_s: int) -> None:
    cache[key] = (time.time() + max(ttl_s, 0), value)


def _sync_common_params() -> dict:
    s = get_settings()
    return {
        "serviceKey": s.tourapi_service_key,
        "MobileOS": s.tourapi_mobile_os,
        "MobileApp": s.tourapi_mobile_app,
        "_type": "json",
    }


def _sync_request(base_url: str, operation: str, params: dict, *, timeout: float | None = None) -> dict:
    """동기 단일 페이지 호출. base.request와 동일한 envelope 처리."""
    s = get_settings()
    if not s.tourapi_service_key:
        raise TourAPIError("TourAPI 키 없음 (DOKKAEBI_TOURAPI_SERVICE_KEY 설정 필요)")

    url = f"{base_url.rstrip('/')}/{operation}"
    full = {"pageNo": 1, "numOfRows": 100, **_sync_common_params(), **params}
    try:
        with httpx.Client(timeout=timeout or s.tourapi_timeout) as client:
            resp = client.get(url, params=full)
    except httpx.HTTPError as e:
        # 원인 없는 빈 메시지 방지 + 재시도 가능 장애로 분류 — base.network_error 공용.
        raise network_error(e, operation) from e

    if resp.status_code >= 400:
        raise TourAPIError(f"TourAPI HTTP {resp.status_code}({operation}): {resp.text[:200]}")
    return _sync_unwrap(resp.json(), operation)


def _sync_unwrap(data: dict, operation: str) -> dict:
    header = data.get("response", {}).get("header", {})
    code = header.get("resultCode")
    if code not in _OK_CODES:
        raise TourAPIError(f"TourAPI 결과오류({operation}): {code}/{header.get('resultMsg')}")

    body = data.get("response", {}).get("body", {})
    raw = body.get("items") or {}
    item = raw.get("item", []) if isinstance(raw, dict) else []
    if isinstance(item, dict):
        item = [item]
    return {
        "items": item,
        "pageNo": body.get("pageNo"),
        "numOfRows": body.get("numOfRows"),
        "totalCount": body.get("totalCount"),
    }


def _sync_request_all(base_url: str, operation: str, params: dict, *, max_pages: int = 20) -> list[dict]:
    """동기 페이지네이션 수집. sync build_route hook에서 사용."""
    first = _sync_request(base_url, operation, {**params, "pageNo": 1})
    items = list(first["items"])
    total = int(first.get("totalCount") or 0)
    rows = int(first.get("numOfRows") or len(items) or 1)
    pages = (total + rows - 1) // rows if rows else 1
    if pages > max_pages:
        logger.warning("%s: %d페이지 중 %d페이지만 수집(max_pages)", operation, pages, max_pages)
        pages = max_pages
    for p in range(2, pages + 1):
        items.extend(_sync_request(base_url, operation, {**params, "pageNo": p})["items"])
    return items
