# ============================================================
# [v1] Mock 임베딩 프로바이더 — 키 없이 baseline 구동용
# pipeline: AI 백엔드 / 임베딩 레이어 (provider 구현체)
# 구현(요약): 텍스트 해시 시드로 결정적 더미 벡터 생성(같은 텍스트 → 같은 벡터).
#            실제 임베딩 API 미호출. 의미 유사도는 없음 — 그래프/인덱스 E2E 배선 검증용.
# 구현일: 2026-06-16 | 작성: kys (semantic-search/kys/v1)
# ============================================================
import hashlib
import random

from app.config import get_settings
from app.embeddings.base import EmbeddingProvider


class MockEmbeddingProvider(EmbeddingProvider):
    """키 없이 의미검색 파이프라인을 돌려보기 위한 목 프로바이더.

    텍스트를 해시로 시드한 PRNG로 고정 차원 벡터를 만든다.
    → 같은 텍스트는 항상 같은 벡터(결정적). 단, '의미'는 담기지 않음(검증 전용).
    """

    def __init__(self, dim: int | None = None) -> None:
        self._dim = dim or get_settings().embed_dim

    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        """텍스트 목록 -> 결정적 더미 벡터 목록 (실제 API 호출 없음)."""
        return [self._vector_for(t) for t in texts]

    def _vector_for(self, text: str) -> list[float]:
        """텍스트 해시를 시드로 [-1,1] 균등분포 벡터 생성(차원=embed_dim)."""
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = random.Random(seed)
        return [rng.uniform(-1.0, 1.0) for _ in range(self._dim)]
