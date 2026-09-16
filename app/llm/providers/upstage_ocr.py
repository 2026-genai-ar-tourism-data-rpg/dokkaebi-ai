# ============================================================
# [v1] Upstage Document OCR 비전 provider — 사진에서 글자만 읽어 판정 재료로 준다
# pipeline: AI 백엔드 / LLM 레이어 (provider 구현체, 사진 검증 전용)
# 구현(요약): Upstage 채팅 모델(solar-pro2/3/4)은 이미지 입력을 거절한다(실측 2026-09-17,
#            "Image input is not allowed for this model"). 대신 같은 키로 쓰는 Document OCR
#            (/v1/document-digitization, model=ocr)로 플레이어 사진의 글자를 읽는다.
#            우리 판정의 가장 강한 신호가 글자(現판·안내판·비석)라 오히려 맞는 도구다 —
#            실측: 흥화문 정면 사진 → "門化興"(우→좌 한자 그대로), 안내판 → "경희궁 흥화문".
#            비전 모델처럼 "같은 대상인가"는 못 판단하므로 match=null 로 돌려주고,
#            photo_verify_service가 글자 대조로 판정을 마무리한다.
#            첫 이미지(플레이어 사진)만 읽는다 — 참조 사진은 글자 대조엔 필요 없고 과금만 는다.
# 구현일: 2026-09-17 | 작성: kys (photo-verify/kys/v1)
# ============================================================
import base64
import json

import httpx

from app.core.exceptions import LLMCallError, LLMRateLimitError
from app.llm.base import LLMProvider


class UpstageOcrProvider(LLMProvider):
    """document-digitization(ocr)로 글자만 읽는 provider. generate(텍스트)는 지원하지 않는다."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 25.0):
        self._url = base_url.rstrip("/") + "/document-digitization"
        self._key = api_key
        self._timeout = timeout

    async def generate(self, prompt: str, **kwargs) -> str:
        raise LLMCallError("UpstageOcrProvider는 텍스트 생성을 지원하지 않는다(사진 검증 전용)")

    async def generate_with_images(self, prompt: str, images: list[str], **kwargs) -> str:
        if not images:
            raise LLMCallError("OCR: 이미지 없음")
        data, mime = _decode_data_url(images[0])
        headers = {"Authorization": f"Bearer {self._key}"}
        files = {"document": ("photo." + ("png" if "png" in mime else "jpg"), data, mime)}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._url, headers=headers, files=files, data={"model": "ocr"})
        except httpx.HTTPError as e:
            raise LLMCallError(f"OCR 호출 네트워크 오류: {e}") from e
        if resp.status_code == 429:
            raise LLMRateLimitError("OCR API 429 (rate limit)")
        if resp.status_code >= 400:
            raise LLMCallError(f"OCR API {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        text = body.get("text") or " ".join(p.get("text", "") for p in body.get("pages", []))
        conf = body.get("confidence")
        try:
            conf = float(conf) if conf is not None else 0.0
        except (TypeError, ValueError):
            conf = 0.0
        # 서비스 계약(JSON)에 맞춰 돌려준다. match=null = "글자로 판정해 달라".
        return json.dumps({
            "match": None,
            "confidence": max(0.0, min(1.0, conf)),
            "text_seen": " ".join(str(text).split())[:300],
            "reason": "OCR 글자 대조",
        }, ensure_ascii=False)


def _decode_data_url(src: str) -> tuple[bytes, str]:
    """data:image/jpeg;base64,... → (bytes, mime). 순수 base64면 JPEG로 본다.
    http(s) URL은 받지 않는다 — 플레이어 사진은 항상 스냅샷(data URI)이어야 한다."""
    if src.startswith("http://") or src.startswith("https://"):
        raise LLMCallError("OCR: 플레이어 사진은 data URI여야 한다(URL 불가)")
    mime = "image/jpeg"
    if src.startswith("data:"):
        head, _, b64 = src.partition(",")
        mime = head[5:].split(";")[0] or mime
    else:
        b64 = src
    try:
        return base64.b64decode(b64, validate=False), mime
    except Exception as e:                      # noqa: BLE001 — 어떤 디코딩 실패든 호출 실패로
        raise LLMCallError(f"OCR: 이미지 디코딩 실패: {e}") from e
