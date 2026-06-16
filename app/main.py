# ============================================================
# [v1] FastAPI 엔트리포인트
# pipeline: AI 백엔드 / 서빙 레이어 (앱 부팅)
# 구현(요약): FastAPI 앱 생성 + 라우터 등록 + 기동 로그
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from fastapi import FastAPI

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
    app.include_router(router)
    logger.info(
        "%s 기동 (env=%s, llm=%s, sem=%d, region_cache=%d)",
        s.app_name, s.env, s.llm_provider, s.llm_semaphore, s.region_cache_max,
    )
    return app


# uvicorn app.main:app
app = create_app()
