# ============================================================
# [v1] 대화 서비스 테스트 — 자유 발화 배선 (dialogue-rework/kys/v1)
# pipeline: AI 백엔드 / 서빙 (테스트)
# 구현(요약): 서버가 player_state.user_input에 실어 보내는 사용자 질문이
#            프롬프트의 '사용자 발화' 자리까지 도달하는지, 그리고 질문이 있을 때는
#            정형 대사 캐시를 타지 않는지 검증한다. LLM·네트워크 0.
# 구현일: 2026-08-19 | 작성: kys (dialogue-rework/kys/v1)
# ============================================================
import asyncio
from unittest.mock import AsyncMock, patch

from app.pipeline.nodes.persona_inject import persona_inject
from app.services.dialogue_service import _utterance


def test_utterance_is_extracted_from_player_state():
    assert _utterance({"user_input": "여기 왜 이름이 이래?"}) == "여기 왜 이름이 이래?"
    assert _utterance({"utterance": " 물어볼 게 있다 "}) == "물어볼 게 있다"
    assert _utterance({"progress": 2}) == ""
    assert _utterance(None) == ""


def test_question_bypasses_the_line_cache():
    """질문이 다른데 같은 대사가 나가면 되묻는 의미가 없다 → 발화가 있으면 캐시 키를 비운다."""
    with (
        patch("app.pipeline.nodes.persona_inject._load_persona", new=AsyncMock(return_value={})),
    ):
        asked = asyncio.run(persona_inject(
            {"node_id": "tour_1", "stage": "등장", "query": "여기 왜 이름이 이래?"}))
        plain = asyncio.run(persona_inject({"node_id": "tour_1", "stage": "등장"}))

    assert asked["cache_key"] == ""                    # 캐시 미사용
    assert plain["cache_key"].endswith("tour_1:등장")   # 정형 대사는 그대로 캐싱
