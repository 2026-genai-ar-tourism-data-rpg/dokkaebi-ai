# ============================================================
# [v1] 노드: persona_inject — 페르소나/진행상황 주입 + 캐시키 산출
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (1번째 노드)
# 구현(요약): 시그니처 + 캐시키 기본 산출. persona 시드 로드는 TODO(이지선)
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from app.pipeline.state import DialogueState


async def persona_inject(state: DialogueState) -> dict:
    """[노드] NPC 페르소나·진행상황을 state에 주입하고 캐시키를 만든다.

    담당: 흐름/주입 시점 = 김예슬 / persona 시드 데이터 = 이지선.
    """
    # TODO(이지선): node_id로 persona 시드(아키타입·모티프·말투) 로드
    node_id = state.get("node_id", "")
    stage = state.get("stage", "등장")
    return {"cache_key": f"npc:{node_id}:{stage}"}
