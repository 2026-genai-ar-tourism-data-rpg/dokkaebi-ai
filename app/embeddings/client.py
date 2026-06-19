# ============================================================
# [v1] 임베딩 클라이언트 래퍼 — 동시성 제한 + 429 백오프 + 배치 병렬
# pipeline: AI 백엔드 / 임베딩 레이어 (빌드타임 인덱싱 · 런타임 쿼리 공용)
# 구현(요약): ①세마포어(config)로 동시 호출 제한 ②embed_batched 배치 병렬 호출
#            ③429(EmbeddingRateLimitError) 지수 백오프+jitter 재시도.
#            provider 선택은 _build_provider 한 곳에서만(=교체 지점). mock/upstage/openai 연결.
# 구현일: 2026-06-16 | 작성: kys (semantic-search/kys/v1)
# ============================================================
import asyncio
import random

from app.config import get_settings
from app.core.exceptions import EmbeddingCallError, EmbeddingRateLimitError
from app.core.logger import get_logger
from app.embeddings.base import EmbeddingProvider
from app.embeddings.providers.mock import MockEmbeddingProvider
from app.embeddings.providers.openai_compatible import OpenAICompatibleEmbeddingProvider

logger = get_logger(__name__)


def _build_provider(name: str) -> EmbeddingProvider:
    """config.embed_provider 이름 -> 프로바이더 인스턴스. **provider 교체는 여기 한 곳에서만.**

    - mock              : 키 없이 구동(결정적 더미 벡터)
    - upstage | openai  : OpenAI 호환(/embeddings) — base_url/model/key는 config
    - 비호환 provider는 providers/ 에 파일 1개 추가 후 여기에 한 줄 분기
    """
    if name == "mock":
        return MockEmbeddingProvider()
    if name in ("upstage", "openai", "openai_compatible"):
        s = get_settings()
        return OpenAICompatibleEmbeddingProvider(
            base_url=s.embed_base_url,
            api_key=s.embed_api_key,
            model=s.embed_model,
            timeout=s.embed_timeout,
        )
    raise EmbeddingCallError(f"미구현 임베딩 provider: {name}")


class EmbeddingClient:
    """임베딩 호출 래퍼 (인덱싱·쿼리에서 공용 권장).

    - 세마포어로 동시 호출 수 제한 (config.embed_semaphore)
    - embed         : 한 배치 호출 (세마포어 + 429 백오프 재시도)
    - embed_batched : 큰 목록을 배치로 쪼개 병렬 호출 (빌드타임 인덱싱용)
    - embed_one     : 단건(쿼리) 편의 메서드
    """

    def __init__(self, provider: EmbeddingProvider | None = None) -> None:
        s = get_settings()
        self._provider = provider or _build_provider(s.embed_provider)
        self._sem = asyncio.Semaphore(s.embed_semaphore)  # 동시 호출 상한
        self._max_retries = s.embed_max_retries
        self._backoff_base = s.embed_backoff_base
        self._backoff_max = s.embed_backoff_max

    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        """한 배치 임베딩 — 세마포어 획득 후 429 백오프 재시도 래핑."""
        if not texts:
            return []
        async with self._sem:
            return await self._call_with_retry(texts, **kwargs)

    async def embed_one(self, text: str, **kwargs) -> list[float]:
        """단건(쿼리) 임베딩 편의 메서드."""
        vectors = await self.embed([text], **kwargs)
        return vectors[0]

    async def embed_batched(
        self, texts: list[str], *, batch_size: int = 64, **kwargs
    ) -> list[list[float]]:
        """큰 목록을 batch_size 단위로 쪼개 병렬 임베딩(세마포어로 동시성 제한, 순서 유지).

        빌드타임 지역 인덱싱(이지선)에서 대량 노드 텍스트를 임베딩할 때 사용.
        동시성은 embed() 내부 세마포어(config.embed_semaphore)가 제한 → gather로 충분.
        """
        batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
        results = await asyncio.gather(*[self.embed(b, **kwargs) for b in batches])
        # 배치별 결과를 평탄화(입력 순서 유지)
        return [vec for batch in results for vec in batch]

    async def _call_with_retry(self, texts: list[str], **kwargs) -> list[list[float]]:
        """429(EmbeddingRateLimitError) 시 지수 백오프(+jitter) 재시도. 소진 시 EmbeddingCallError."""
        attempt = 0
        while True:
            try:
                return await self._provider.embed(texts, **kwargs)
            except EmbeddingRateLimitError:
                attempt += 1
                if attempt > self._max_retries:
                    logger.error("임베딩 429 재시도 소진 (%d회)", self._max_retries)
                    raise EmbeddingCallError("임베딩 rate limit 재시도 소진")
                delay = min(self._backoff_base * (2 ** (attempt - 1)), self._backoff_max)
                delay += random.uniform(0, delay * 0.1)  # thundering herd 방지 jitter
                logger.warning(
                    "임베딩 429 → %.2fs 후 재시도 (%d/%d)", delay, attempt, self._max_retries
                )
                await asyncio.sleep(delay)
