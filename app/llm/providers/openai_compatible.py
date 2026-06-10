# ============================================================
# [v1] OpenAI 호환 LLM provider (Upstage Solar / OpenAI 등)
# pipeline: AI 백엔드 / LLM 레이어 (provider 구현체)
# 구현(요약): httpx로 {base_url}/chat/completions 호출. 429 → LLMRateLimitError.
#            base_url/model/key는 config 주입 → OpenAI 호환끼리는 config만 바꾸면 교체(파일 0개)
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
import httpx

from app.core.exceptions import LLMCallError, LLMRateLimitError
from app.llm.base import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    """OpenAI 호환 chat/completions 엔드포인트용 단일 provider.

    Upstage(Solar)·OpenAI 등 호환 API는 base_url/model/key만 바꾸면 그대로 동작.
    → 비호환(HyperCLOVA/Claude)만 별도 provider 파일을 추가하면 됨.
    호출 재시도/세마포어는 provider가 아니라 LLMClient가 담당(로직 통일).
    """

    def __init__(self, base_url, api_key, model, temperature, max_tokens, timeout):
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout

    async def generate(self, prompt: str, **kwargs) -> str:
        """프롬프트 1건 -> 생성 텍스트. 429는 LLMRateLimitError로 변환(상위에서 백오프 재시도)."""
        headers = {"Authorization": f"Bearer {self._key}"}
        payload = {
            "model": kwargs.get("model", self._model),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", self._temperature),
            "max_tokens": kwargs.get("max_tokens", self._max_tokens),
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, headers=headers, json=payload)
        except httpx.HTTPError as e:
            # 네트워크/타임아웃 등 → 호출 실패로 변환
            raise LLMCallError(f"LLM 호출 네트워크 오류: {e}") from e

        if resp.status_code == 429:
            raise LLMRateLimitError("LLM API 429 (rate limit)")
        if resp.status_code >= 400:
            raise LLMCallError(f"LLM API {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        return data["choices"][0]["message"]["content"]
