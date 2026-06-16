# ============================================================
# [v1] 임베딩 프로바이더 추상 인터페이스
# pipeline: AI 백엔드 / 임베딩 레이어 (provider 교체 가능)
# 구현(요약): embed 추상 메서드 정의. 구현체는 providers/ 에. 429는 EmbeddingRateLimitError로.
# 구현일: 2026-06-16 | 작성: kys (semantic-search/kys/v1)
# ============================================================
from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """임베딩 프로바이더 추상 인터페이스. provider 교체 가능(mock/upstage/openai)."""

    @abstractmethod
    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        """텍스트 목록 -> 임베딩 벡터 목록(입력 순서 유지).

        구현 규약: 429(rate limit) 응답은 반드시 EmbeddingRateLimitError로 변환해 raise.
        (EmbeddingClient가 그 예외를 잡아 백오프 재시도함)
        """
        ...
