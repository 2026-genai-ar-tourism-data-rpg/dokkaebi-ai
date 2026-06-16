# ============================================================
# [v1] LLM 클라이언트 래퍼 — 동시성 제한 + 429 백오프 + 병렬 호출
# pipeline: AI 백엔드 / LLM 레이어 (핫패스 공용)
# 구현(요약): ①세마포어(config)로 동시 호출 제한 ②generate_many 병렬 호출
#            ③429(LLMRateLimitError) 지수 백오프+jitter 재시도.
#            provider 선택은 _build_provider 한 곳에서만(=교체 지점). mock/upstage/openai 연결.
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
import asyncio
import random

from app.config import get_settings
from app.core.exceptions import LLMCallError, LLMRateLimitError
from app.core.logger import get_logger
from app.llm.base import LLMProvider
from app.llm.providers.mock import MockProvider
from app.llm.providers.openai_compatible import OpenAICompatibleProvider

logger = get_logger(__name__)


def _build_provider(name: str) -> LLMProvider:
    """config.llm_provider 이름 -> 프로바이더 인스턴스. **provider 교체는 여기 한 곳에서만.**

    - mock              : 키 없이 구동
    - upstage | openai  : OpenAI 호환(같은 클래스) — base_url/model/key는 config
    - 비호환(HyperCLOVA/Claude): providers/ 에 파일 1개 추가 후 여기에 한 줄 분기
    """
    if name == "mock":
        return MockProvider()
    if name in ("upstage", "openai", "openai_compatible"):
        s = get_settings()
        return OpenAICompatibleProvider(
            base_url=s.llm_base_url,
            api_key=s.llm_api_key,
            model=s.llm_model,
            temperature=s.llm_temperature,
            max_tokens=s.llm_max_tokens,
            timeout=s.llm_timeout,
        )
    # TODO: HyperCLOVA / Claude 등 비(非)OpenAI호환 provider는 여기에 분기 추가
    raise LLMCallError(f"미구현 LLM provider: {name}")


class LLMClient:
    """LLM 호출 래퍼 (핫패스에서 단일 인스턴스 공용 권장).

    - 세마포어로 동시 호출 수 제한 (config.llm_semaphore)
    - generate     : 단일 호출 (세마포어 + 429 백오프 재시도)
    - generate_many: 다건 병렬 호출 (세마포어 공유로 동시성 제한, 순서 유지)
    """

    def __init__(self, provider: LLMProvider | None = None) -> None:
        s = get_settings()
        self._provider = provider or _build_provider(s.llm_provider)
        self._sem = asyncio.Semaphore(s.llm_semaphore)  # 동시 호출 상한
        self._max_retries = s.llm_max_retries
        self._backoff_base = s.llm_backoff_base
        self._backoff_max = s.llm_backoff_max

    async def generate(self, prompt: str, **kwargs) -> str:
        """단일 LLM 호출 — 세마포어 획득 후 429 백오프 재시도 래핑."""
        async with self._sem:
            return await self._call_with_retry(prompt, **kwargs)

    async def generate_many(self, prompts: list[str], **kwargs) -> list[str]:
        """여러 프롬프트 병렬 호출. 각 호출이 세마포어를 공유해 동시성 제한됨."""
        return await asyncio.gather(*[self.generate(p, **kwargs) for p in prompts])

    async def _call_with_retry(self, prompt: str, **kwargs) -> str:
        """429(LLMRateLimitError) 발생 시 지수 백오프(+jitter) 재시도. 소진 시 LLMCallError."""
        attempt = 0
        while True:
            try:
                return await self._provider.generate(prompt, **kwargs)
            except LLMRateLimitError:
                attempt += 1
                if attempt > self._max_retries:
                    logger.error("LLM 429 재시도 소진 (%d회)", self._max_retries)
                    raise LLMCallError("LLM rate limit 재시도 소진")
                delay = min(self._backoff_base * (2 ** (attempt - 1)), self._backoff_max)
                delay += random.uniform(0, delay * 0.1)  # thundering herd 방지 jitter
                logger.warning(
                    "LLM 429 → %.2fs 후 재시도 (%d/%d)", delay, attempt, self._max_retries
                )
                await asyncio.sleep(delay)
