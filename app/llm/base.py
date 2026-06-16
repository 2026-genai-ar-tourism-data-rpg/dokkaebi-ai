# ============================================================
# [v1] LLM 프로바이더 추상 인터페이스
# pipeline: AI 백엔드 / LLM 레이어 (provider 교체 가능)
# 구현(요약): generate 추상 메서드 정의. 구현체는 providers/ 에. 429는 LLMRateLimitError로.
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """LLM 프로바이더 추상 인터페이스. provider 교체 가능(mock/hyperclova/claude/openai)."""

    @abstractmethod
    async def generate(self, prompt: str, **kwargs) -> str:
        """프롬프트 -> 생성 텍스트.
        구현 규약: 429(rate limit) 응답은 반드시 LLMRateLimitError로 변환해 raise.
        (LLMClient가 그 예외를 잡아 백오프 재시도함)
        """
        ...
