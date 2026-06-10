# ============================================================
# [v1] 공통 예외 — 도메인 예외 계층
# pipeline: 공통 인프라
# 구현(요약): 베이스 예외 + LLM rate limit(429)/호출 실패 예외
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================


class DokkaebiAIError(Exception):
    """dokkaebi-ai 공통 베이스 예외."""


class LLMRateLimitError(DokkaebiAIError):
    """LLM 429(rate limit). LLMClient가 백오프 재시도 대상으로 처리.
    → provider 구현체는 429 응답을 이 예외로 변환해서 raise해야 함."""


class LLMCallError(DokkaebiAIError):
    """LLM 호출 실패(재시도 소진·미구현 provider 등)."""
