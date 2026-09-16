# ============================================================
# [v1] Mock LLM 프로바이더 — 키 없이 baseline 구동용
# pipeline: AI 백엔드 / LLM 레이어 (provider 구현체)
# 구현(요약): 고정 더미 대사 반환(실제 LLM 미호출). 실제 provider 붙기 전 그래프 E2E 검증용
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from app.llm.base import LLMProvider


class MockProvider(LLMProvider):
    """키 없이 파이프라인을 끝까지 돌려보기 위한 목 프로바이더."""

    async def generate(self, prompt: str, **kwargs) -> str:
        """더미 도깨비 대사 반환 (실제 LLM 호출 없음)."""
        return "[mock 도깨비] 허허, 아직 진짜 LLM이 붙지 않았느니라."

    async def generate_with_images(self, prompt: str, images: list[str], **kwargs) -> str:
        """사진 검증용 더미 판정. 이미지가 하나도 없으면 불일치, 있으면 일치 — 테스트가 예측 가능해야 한다."""
        if not images:
            return '{"match": false, "confidence": 0.1, "text_seen": "", "reason": "[mock] 이미지 없음"}'
        return '{"match": true, "confidence": 0.9, "text_seen": "[mock]", "reason": "[mock] 이미지 수신"}'
