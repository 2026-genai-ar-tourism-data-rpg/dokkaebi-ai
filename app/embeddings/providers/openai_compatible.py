# ============================================================
# [v1] OpenAI 호환 임베딩 provider (Upstage / OpenAI 등)
# pipeline: AI 백엔드 / 임베딩 레이어 (provider 구현체)
# 구현(요약): httpx로 {base_url}/embeddings 호출. 429 → EmbeddingRateLimitError.
#            base_url/model/key는 config 주입 → 호환끼리는 config만 바꾸면 교체(파일 0개)
# 구현일: 2026-06-16 | 작성: kys (semantic-search/kys/v1)
# ============================================================
import httpx

from app.core.exceptions import EmbeddingCallError, EmbeddingRateLimitError
from app.embeddings.base import EmbeddingProvider


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """OpenAI 호환 /embeddings 엔드포인트용 단일 provider.

    Upstage(solar-embedding)·OpenAI(text-embedding-3-*) 등 호환 API는
    base_url/model/key만 바꾸면 그대로 동작.
    호출 재시도/세마포어는 provider가 아니라 EmbeddingClient가 담당(로직 통일).
    """

    def __init__(self, base_url, api_key, model, timeout):
        self._url = base_url.rstrip("/") + "/embeddings"
        self._key = api_key
        self._model = model
        self._timeout = timeout

    async def embed(self, texts: list[str], **kwargs) -> list[list[float]]:
        """텍스트 배치 -> 벡터 배치. 429는 EmbeddingRateLimitError로 변환(상위에서 백오프)."""
        headers = {"Authorization": f"Bearer {self._key}"}
        payload = {"model": kwargs.get("model", self._model), "input": texts}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, headers=headers, json=payload)
        except httpx.HTTPError as e:
            raise EmbeddingCallError(f"임베딩 호출 네트워크 오류: {e}") from e

        if resp.status_code == 429:
            raise EmbeddingRateLimitError("임베딩 API 429 (rate limit)")
        if resp.status_code >= 400:
            raise EmbeddingCallError(f"임베딩 API {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        # OpenAI 호환 응답: {"data": [{"embedding": [...], "index": 0}, ...]}
        items = sorted(data["data"], key=lambda d: d["index"])
        return [item["embedding"] for item in items]
