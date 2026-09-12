# ============================================================
# [v1] 요청 로깅 미들웨어 — 요청 1건의 시작·끝·소요시간
# pipeline: AI 백엔드 / 서빙 레이어 (관측)
# 구현(요약): 요청마다 req_id를 발급해 컨텍스트에 심고(=이후 모든 로그에 자동 부착),
#            들어올 때와 나갈 때 한 줄씩 남긴다. 응답에는 X-Request-Id를 실어
#            앱·서버 로그와 대조할 수 있게 한다.
#            유저는 헤더(X-User-Id/X-User-Name)가 있으면 여기서, 없으면 라우트가
#            본문을 파싱한 뒤 채운다 — 그래서 '완료' 줄에는 유저가 찍힌다.
#            ⚠️ 본문을 읽지 않는다. 미들웨어에서 body를 소비하면 라우트가 다시 못 읽는다.
# 구현일: 2026-09-12 | 작성: kys (ops-logging/kys/v1)
# ============================================================
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.logger import get_logger
from app.core.reqctx import bind_request, bind_user, current_request_id, current_user

logger = get_logger(__name__)

# 헬스체크는 컨테이너가 5초마다 두드린다 — 실시간 로그를 보는 눈을 가리므로 제외.
_QUIET_PATHS = {"/v1/health"}

# 느린 요청 기준(ms). 경로마다 '정상 속도'가 달라 한 값으로 두면 경고가 의미를 잃는다.
# 시나리오 생성은 LLM을 수십 번 타 10초대가 정상 — 3초 기준이면 매번 경고가 떠서
# 진짜 이상(예: 40초)이 묻힌다.
_SLOW_MS_DEFAULT = 3000
_SLOW_MS_BY_PATH = {
    "/v1/scenarios": 25000,      # 노드 8개 × (대사+미션) 생성. 25초 넘으면 이상.
    "/v1/dialogue/turn": 8000,   # LLM 1~2콜. 사용자가 화면 앞에서 기다리는 구간.
}


class RequestLogMiddleware(BaseHTTPMiddleware):
    """요청 진입/종료 로깅 + 요청 컨텍스트 바인딩."""

    async def dispatch(self, request: Request, call_next):
        bind_request()
        # 서버가 아직 안 보내지만, 보내기 시작하면 그 즉시 유저가 찍힌다(추가 작업 불필요).
        # ⚠️ HTTP 헤더는 latin-1이라 한글 닉네임을 그대로 실으면 깨지거나 전송이 막힌다.
        #    서버는 ASCII인 X-User-Id를 보내는 게 안전하다(닉네임이 필요하면 percent-encoding).
        uid = request.headers.get("X-User-Id")
        uname = request.headers.get("X-User-Name")
        if uid or uname:
            bind_user(uid, uname)

        path = request.url.path
        quiet = path in _QUIET_PATHS
        if not quiet:
            q = str(request.url.query or "")
            logger.info("▶ %s %s%s", request.method, path, f"?{q}" if q else "")

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # 응답 변환은 errors.py가 한다. 여기서는 '얼마 만에 터졌나'만 남기고 다시 던진다.
            ms = (time.perf_counter() - started) * 1000
            logger.exception("✖ %s %s — %.0fms 만에 예외", request.method, path, ms)
            raise

        ms = (time.perf_counter() - started) * 1000
        if not quiet:
            mark = "✔" if response.status_code < 400 else "✖"
            limit = _SLOW_MS_BY_PATH.get(path, _SLOW_MS_DEFAULT)
            slow = f"  ⚠느림(기준 {limit // 1000}s)" if ms >= limit else ""
            logger.info(
                "%s %s %s → %d (%.0fms)%s",
                mark, request.method, path, response.status_code, ms, slow,
            )
        response.headers["X-Request-Id"] = current_request_id()
        return response


__all__ = ["RequestLogMiddleware", "current_user"]
