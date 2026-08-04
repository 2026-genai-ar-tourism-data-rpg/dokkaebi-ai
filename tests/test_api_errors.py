# ============================================================
# [v1] API 에러 계약 테스트 — 도메인 예외 → HTTP 상태코드 (이슈 #39)
# pipeline: AI 백엔드 / 서빙 레이어 (테스트, 네트워크 0 — 라우트를 예외로 스텁)
# 구현(요약): DokkaebiAIError=422 / rate limit=503+Retry-After / 업스트림=502 / 그 외=500.
#            스택트레이스가 응답 바디에 새지 않는지도 함께 검증.
# 구현일: 2026-08-02 | 작성: kys (branch-parity/kys/v1)
# ============================================================
import pytest
from fastapi.testclient import TestClient

from app.core.exceptions import (
    DokkaebiAIError,
    EmbeddingRateLimitError,
    LLMCallError,
    LLMRateLimitError,
)
from app.main import create_app


def _client_raising(exc: Exception) -> TestClient:
    """지정 예외를 던지는 임시 라우트를 붙인 테스트 클라이언트.

    실제 시나리오 생성을 타지 않으므로 네트워크·LLM 호출이 없다(결정론).
    raise_server_exceptions=False → 핸들러가 만든 응답을 그대로 관찰.
    """
    app = create_app()

    @app.get("/_boom")
    async def _boom():
        raise exc

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize(
    "exc, expected",
    [
        (DokkaebiAIError("반경 300m 내 관광지 없음"), 422),
        (LLMRateLimitError("429 소진"), 503),
        (EmbeddingRateLimitError("429 소진"), 503),
        (LLMCallError("provider 실패"), 502),
        (RuntimeError("예상 못 한 결함"), 500),
    ],
)
def test_exception_maps_to_status(exc, expected):
    """도메인 예외가 각자의 HTTP 상태코드로 변환된다(500 일괄 아님)."""
    res = _client_raising(exc).get("/_boom")
    assert res.status_code == expected


def test_domain_error_body_is_structured_and_actionable():
    """422 바디에 앱이 분기할 코드 + 사용자에게 보여줄 원인이 담긴다."""
    res = _client_raising(DokkaebiAIError("반경 300m 내 관광지 없음")).get("/_boom")
    body = res.json()
    assert body["error"]["code"] == "domain_error"
    assert "반경 300m 내 관광지 없음" in body["error"]["message"]


def test_rate_limit_sets_retry_after():
    """503엔 재시도 대기 힌트(Retry-After)가 붙는다."""
    res = _client_raising(LLMRateLimitError("429 소진")).get("/_boom")
    assert int(res.headers["Retry-After"]) > 0


def test_unhandled_error_does_not_leak_internals():
    """미처리 예외는 트레이스·예외 메시지를 응답 바디로 흘리지 않는다."""
    res = _client_raising(RuntimeError("내부 비밀 경로 /secret/path")).get("/_boom")
    raw = res.text
    assert "Traceback" not in raw
    assert "/secret/path" not in raw
    assert res.json()["error"]["code"] == "internal_error"
