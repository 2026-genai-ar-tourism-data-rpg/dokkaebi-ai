# ============================================================
# [v1] 공통 로거 — 전 모듈 공용 로깅 팩토리
# pipeline: 공통 인프라
# 구현(요약): 모듈명 기반 로거 생성, 공통 포맷, 핸들러 중복 방지, config의 log_level 적용
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ------------------------------------------------------------
# [v2] 모든 로그 줄에 유저·요청ID를 붙인다 — 운영 테스트용 상관관계.
# 구현(요약): reqctx(contextvars)를 읽는 Filter를 핸들러에 달았다. 그래서 기존 로그
#            호출부를 한 줄도 안 고쳐도 전부 "누구의 어느 요청인지"가 찍힌다.
#            포맷: 시각 | 레벨 | [유저 요청id] | 모듈 | 메시지
#            모듈명은 app. 접두어를 떼어 폭을 줄인다(app.scenario.generator → scenario.generator).
# 구현일: 2026-09-12 | 작성: kys (ops-logging/kys/v1)
# ============================================================
import logging
import sys

from app.config import get_settings
from app.core.reqctx import current_request_id, current_user

# [유저 요청id] 열을 고정폭으로 둬야 눈으로 훑을 때 줄이 맞는다.
_FORMAT = "%(asctime)s | %(levelname)-7s | %(ctx)-31s | %(short_name)-26s | %(message)s"
_DATEFMT = "%m-%d %H:%M:%S"


class _ContextFilter(logging.Filter):
    """레코드마다 현재 요청의 유저·요청ID를 채워 넣는다.

    Filter를 쓰는 이유: 포맷 문자열이 %(ctx)s를 참조하는데 그 값을 만들어 줄 곳이
    필요하고, LogRecord 생성 시점(=로그를 찍는 그 async 태스크)에서 읽어야
    contextvars가 올바른 값을 준다. Formatter에서 읽으면 핸들러가 다른
    태스크에서 돌 때 값이 어긋날 수 있다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.ctx = f"{current_user()} {current_request_id()}"
        name = record.name
        record.short_name = name[4:] if name.startswith("app.") else name
        return True


def get_logger(name: str) -> logging.Logger:
    """모듈명으로 공통 포맷 로거 반환. 이미 핸들러가 있으면 재사용(중복 부착 방지)."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    settings = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))
    handler.addFilter(_ContextFilter())
    logger.addHandler(handler)
    logger.setLevel(settings.log_level)
    logger.propagate = False
    return logger
