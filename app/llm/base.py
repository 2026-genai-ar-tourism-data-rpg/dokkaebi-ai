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

    async def generate_with_images(self, prompt: str, images: list[str], **kwargs) -> str:
        """프롬프트 + 이미지들(URL 또는 data: URI) -> 생성 텍스트. 사진 검증(photo_verify)이 쓴다.

        기본 구현은 미지원 — 텍스트 전용 provider가 조용히 이미지를 버리고 답하면
        "검증됐다"는 거짓 결과가 나가므로, 명시적으로 실패시킨다.
        구현 규약은 generate와 같다(429 → LLMRateLimitError).
        """
        from app.core.exceptions import LLMCallError
        raise LLMCallError(f"{type(self).__name__}: 이미지 입력 미지원")
