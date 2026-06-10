# ============================================================
# [v1] 공통 로거 — 전 모듈 공용 로깅 팩토리
# pipeline: 공통 인프라
# 구현(요약): 모듈명 기반 로거 생성, 공통 포맷, 핸들러 중복 방지, config의 log_level 적용
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
import logging
import sys

from app.config import get_settings

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def get_logger(name: str) -> logging.Logger:
    """모듈명으로 공통 포맷 로거 반환. 이미 핸들러가 있으면 재사용(중복 부착 방지)."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(settings.log_level)
    logger.propagate = False
    return logger
