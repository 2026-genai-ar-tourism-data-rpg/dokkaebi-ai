# ============================================================
# [v1] TourAPI 빅데이터 계열 클라이언트 — 연관·집중률·중심·방문자수
# pipeline: AI 백엔드 / 외부 데이터 (비인기 라벨링·연관 동선 task의 데이터 접근층)
# 구현(요약): 4개 서비스 호출 로직. 공통 호출부(base.request_all) 위에 서비스별 메서드.
#            ⚠️ 데이터 '사용'(비인기 컷오프·연관 동선)은 별도 task(박준형 EDA). 여기는 '접근'만.
#            ⚠️ 빅데이터 코드(tAtsCd 등)는 KorService2 contentId와 다름 → 매칭 별도.
# 구현일: 2026-06-18 | 작성: kys (bigdata-client/kys/v1)
# 참고: report/외부API 빅데이터 정리 문서
# ============================================================
from datetime import date

from app.config import get_settings
from app.tourapi.base import request_all


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
