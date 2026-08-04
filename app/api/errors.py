# ============================================================
# [v1] API 예외 핸들러 — 도메인 예외 → HTTP 상태코드 매핑
# pipeline: AI 백엔드 / 서빙 레이어 (에러 계약)
# 구현(요약): DokkaebiAIError 계층을 앱이 분기 가능한 JSON 에러 바디로 변환.
#            도메인 실패=422 / rate limit=503(Retry-After) / 업스트림 실패=502 / 그 외=500.
#            스택트레이스는 로그로만 남기고 응답 바디엔 절대 노출하지 않는다.
# 구현일: 2026-08-02 | 작성: kys (branch-parity/kys/v1) · 이슈 #39
# ============================================================
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import (
    DokkaebiAIError,
    EmbeddingCallError,
    EmbeddingRateLimitError,
    LLMCallError,
    LLMRateLimitError,
)
from app.core.logger import get_logger

logger = get_logger(__name__)

# 앱이 사용자 안내 문구를 고를 수 있게 하는 에러 코드(문자열 계약).
CODE_DOMAIN = "domain_error"          # 입력을 바꾸면 해결되는 실패(반경 확대 등)
CODE_RATE_LIMIT = "rate_limited"      # 429 소진 — 잠시 후 재시도
CODE_UPSTREAM = "upstream_error"      # LLM/임베딩 호출 실패
CODE_INTERNAL = "internal_error"      # 예기치 못한 서버 오류


def _body(code: str, message: str) -> dict:
    """앱이 분기할 수 있는 통일된 에러 바디. 내부 예외 타입·트레이스는 담지 않는다."""
    return {"error": {"code": code, "message": message}}


def register_error_handlers(app: FastAPI) -> None:
    """FastAPI 앱에 도메인 예외 핸들러를 등록한다.

    Starlette가 예외의 MRO를 따라 핸들러를 찾으므로, 하위 예외(rate limit 등)가
    상위 DokkaebiAIError 핸들러보다 우선 매칭된다 → 등록 순서에 의존하지 않는다.
    담당: 에러 계약 = 김예슬.
    """
    s = get_settings()
    retry_after = str(int(max(s.llm_backoff_max, s.embed_backoff_max)))

    @app.exception_handler(LLMRateLimitError)
    @app.exception_handler(EmbeddingRateLimitError)
    async def _rate_limited(request: Request, exc: Exception) -> JSONResponse:
        """429 소진 — 앱은 재시도 가능. Retry-After로 대기 힌트를 준다."""
        logger.warning("rate limit 소진: %s %s — %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=503,
            content=_body(CODE_RATE_LIMIT, "요청이 몰려 잠시 지연되고 있느니라. 잠시 후 다시 시도해다오."),
            headers={"Retry-After": retry_after},
        )

    @app.exception_handler(LLMCallError)
    @app.exception_handler(EmbeddingCallError)
    async def _upstream_failed(request: Request, exc: Exception) -> JSONResponse:
        """LLM/임베딩 업스트림 실패 — 서버 자체 결함이 아니므로 502."""
        logger.error("업스트림 호출 실패: %s %s — %s", request.method, request.url.path, exc)
        return JSONResponse(
            status_code=502,
            content=_body(CODE_UPSTREAM, "도깨비가 잠시 말을 잃었느니라. 잠시 후 다시 시도해다오."),
        )

    @app.exception_handler(DokkaebiAIError)
    async def _domain_error(request: Request, exc: DokkaebiAIError) -> JSONResponse:
        """도메인 실패(반경 내 관광지 없음 등) — 입력을 바꾸면 풀리므로 4xx.

        예외 메시지는 원인이 사용자 입력이라 그대로 노출해도 안전하다(좌표·반경 수준).
        """
        logger.info("도메인 실패: %s %s — %s", request.method, request.url.path, exc)
        return JSONResponse(status_code=422, content=_body(CODE_DOMAIN, str(exc)))

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        """미처리 예외 — 트레이스는 로그에만, 응답엔 일반 메시지만."""
        logger.exception("미처리 예외: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content=_body(CODE_INTERNAL, "서버에 예기치 못한 문제가 생겼느니라."),
        )
