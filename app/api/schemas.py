# ============================================================
# [v1] API 스키마 — NPC 대화 요청/응답 (Pydantic)
# pipeline: AI 백엔드 / 서빙 레이어 (계약)
# 구현(요약): DialogueRequest / DialogueResponse 정의
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from pydantic import BaseModel, Field


class DialogueRequest(BaseModel):
    """NPC 대화 요청 — 게임 서버(dokkaebi-server)가 내부 HTTP로 호출."""

    node_id: str = Field(..., description="장소 노드 ID")
    stage: str = Field("등장", description="등장|의뢰|힌트|완료")
    player_state: dict = Field(default_factory=dict, description="진행도·보유 조각·이전 대화 요약")


class DialogueResponse(BaseModel):
    """NPC 대화 응답."""

    response: str
    cache_hit: bool = False
