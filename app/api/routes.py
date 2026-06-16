# ============================================================
# [v1] API 라우트 — NPC 대화 엔드포인트
# pipeline: AI 백엔드 / 서빙 레이어 (진입점)
# 구현(요약): POST /v1/dialogue (대화 생성) + GET /v1/health
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from fastapi import APIRouter

from app.api.schemas import DialogueRequest, DialogueResponse
from app.services.dialogue_service import run_dialogue

router = APIRouter(prefix="/v1", tags=["dialogue"])


@router.post("/dialogue", response_model=DialogueResponse)
async def dialogue(req: DialogueRequest) -> DialogueResponse:
    """[엔드포인트] NPC 대화 생성 — 게임 서버 내부 호출용."""
    text, hit = await run_dialogue(req.node_id, req.stage, req.player_state)
    return DialogueResponse(response=text, cache_hit=hit)


@router.get("/health")
async def health() -> dict:
    """[엔드포인트] 헬스체크."""
    return {"status": "ok"}
