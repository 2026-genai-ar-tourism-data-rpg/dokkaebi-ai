# ============================================================
# [v1] TourAPI 공통 호출부 — 모든 B551011 서비스 공용
# pipeline: AI 백엔드 / 외부 데이터 (공통 모듈)
# 구현(요약): 공통 파라미터(serviceKey·MobileOS·_type) 주입 + httpx GET
#            + resultCode 검증(HTTP200≠성공) + items 언랩 + 페이지네이션(request_all).
#            서비스별 normalize는 각 client가 담당(모듈 분리).
# 구현일: 2026-06-18 | 작성: kys (bigdata-client/kys/v1)
# ============================================================
import httpx

from app.config import get_settings
from app.core.exceptions import DokkaebiAIError
from app.core.logger import get_logger

logger = get_logger(__name__)

_OK_CODES = ("0000", "00", "0")  # 서비스별로 정상 코드 표기가 약간 다름


class TourAPIError(DokkaebiAIError):
    """TourAPI 호출 실패(에러 resultCode·네트워크·키 없음 등)."""


def _common_params() -> dict:
    """모든 호출에 공통으로 들어가는 인증·환경 파라미터."""
    s = get_settings()
    return {
        "serviceKey": s.tourapi_service_key,  # 디코딩 키 권장(httpx가 자동 인코딩)
        "MobileOS": s.tourapi_mobile_os,
        "MobileApp": s.tourapi_mobile_app,
        "_type": "json",
    }


async def request(base_url: str, operation: str, params: dict, *, timeout: float | None = None) -> dict:
    """단일 페이지 호출 → {items, pageNo, numOfRows, totalCount}.

    공통 파라미터 주입 + resultCode 검증 + items 언랩까지. 서비스별 정규화는 호출측에서.
    """
    s = get_settings()
    if not s.tourapi_service_key:
        raise TourAPIError("TourAPI 키 없음 (DOKKAEBI_TOURAPI_SERVICE_KEY 설정 필요)")
    url = f"{base_url.rstrip('/')}/{operation}"
    full = {"pageNo": 1, "numOfRows": 100, **_common_params(), **params}
    try:
        async with httpx.AsyncClient(timeout=timeout or s.tourapi_timeout) as client:
            resp = await client.get(url, params=full)
    except httpx.HTTPError as e:
        raise TourAPIError(f"TourAPI 네트워크 오류({operation}): {e}") from e
    if resp.status_code >= 400:
        raise TourAPIError(f"TourAPI HTTP {resp.status_code}({operation}): {resp.text[:200]}")
    return _unwrap(resp.json(), operation)


def _unwrap(data: dict, operation: str) -> dict:
    """공통 응답 envelope → items 배열 + 페이지 메타. resultCode 비정상이면 raise."""
    header = data.get("response", {}).get("header", {})
    code = header.get("resultCode")
    if code not in _OK_CODES:
        raise TourAPIError(f"TourAPI 결과오류({operation}): {code}/{header.get('resultMsg')}")
    body = data.get("response", {}).get("body", {})
    raw = body.get("items") or {}
    item = raw.get("item", []) if isinstance(raw, dict) else []
    if isinstance(item, dict):  # 단건이면 dict로 옴 → 리스트화
        item = [item]
    return {
        "items": item,
        "pageNo": body.get("pageNo"),
        "numOfRows": body.get("numOfRows"),
        "totalCount": body.get("totalCount"),
    }


async def request_all(base_url: str, operation: str, params: dict, *, max_pages: int = 20) -> list[dict]:
    """totalCount 기반 페이지네이션으로 전체 items 수집(상한 max_pages).

    배치(노드 빌더·EDA)에서 시군구 전체를 받을 때 사용.
    """
    first = await request(base_url, operation, {**params, "pageNo": 1})
    items = list(first["items"])
    total = int(first.get("totalCount") or 0)
    rows = int(first.get("numOfRows") or len(items) or 1)
    pages = (total + rows - 1) // rows if rows else 1
    if pages > max_pages:
        logger.warning("%s: %d페이지 중 %d페이지만 수집(max_pages)", operation, pages, max_pages)
        pages = max_pages
    for p in range(2, pages + 1):
        items.extend((await request(base_url, operation, {**params, "pageNo": p}))["items"])
    return items
