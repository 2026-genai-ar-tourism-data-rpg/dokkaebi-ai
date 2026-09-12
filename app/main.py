# ============================================================
# [v1] FastAPI 엔트리포인트
# pipeline: AI 백엔드 / 서빙 레이어 (앱 부팅)
# 구현(요약): FastAPI 앱 생성 + 라우터 등록 + 예외 핸들러 등록 + 기동 로그
# 구현일: 2026-06-10 (예외 핸들러 추가: 2026-08-02) | 작성: kys (base-pipeline/kys/v1)
# ------------------------------------------------------------
# [v2] 요청 로깅 미들웨어 등록 + 기동 로그에 운영 설정 노출.
# 구현(요약): 실기기 테스트 중 "어디서 터졌나"를 로그만으로 좇으려면 요청 단위 경계가
#            필요하다. 기동 로그에는 TourAPI·구글키·임베딩 유무를 같이 찍는다 —
#            키 누락은 예외 없이 조용히 폴백해서, 기동 시점에 안 보면 못 잡는다.
# 구현일: 2026-09-12 | 작성: kys (ops-logging/kys/v1)
# ============================================================
from fastapi import FastAPI

from app.api.errors import register_error_handlers
from app.api.middleware import RequestLogMiddleware
from app.api.routes import router
from app.config import get_settings
from app.core.logger import get_logger

logger = get_logger(__name__)


def create_app() -> FastAPI:
    """FastAPI 앱 생성 + 라우터 등록.

    담당: 서빙 골격 = 김예슬 + 정찬희.
    """
    s = get_settings()
    app = FastAPI(title=s.app_name, version="v1")
    app.add_middleware(RequestLogMiddleware)   # 요청 단위 로그 + req_id 컨텍스트
    app.include_router(router)
    register_error_handlers(app)        # 도메인 예외 → HTTP 계약(#39)
    logger.info(
        "%s 기동 (env=%s, llm=%s/%s, sem=%d, region_cache=%d, log=%s)",
        s.app_name, s.env, s.llm_provider, s.llm_model,
        s.llm_semaphore, s.region_cache_max, s.log_level,
    )
    # 외부 키는 없어도 예외 없이 폴백한다 — 기동 때 안 찍어두면 "왜 가격대가 다 비지"를
    # 나중에 앱 화면만 보고 역추적하게 된다(2026-09-12 실제로 겪음).
    logger.info(
        "외부 연동: TourAPI=%s · GooglePlaces=%s · 임베딩=%s · 캐시=%s · 식음%d곳/코스",
        "키있음" if s.tourapi_service_key else "키없음(mock 종로)",
        "키있음" if s.google_maps_api_key else "키없음(가격대 전부 미상)",
        s.embed_provider,
        s.cache_backend,
        s.scenario_food_per_route,
    )
    return app


# uvicorn app.main:app
app = create_app()
