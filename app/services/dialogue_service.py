# ============================================================
# [v1] 대화 서비스 — 그래프 invoke 래핑
# pipeline: AI 백엔드 / 서빙↔오케스트레이션 연결
# 구현(요약): 컴파일된 LangGraph 1회 빌드 후 ainvoke로 실행, 응답 추출
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from app.core.logger import get_logger
from app.pipeline.graph import build_graph
from app.pipeline.state import DialogueState

logger = get_logger(__name__)

# 컴파일된 그래프는 1회만 빌드(stateless) — 호출마다 state만 주입
_graph = build_graph()


async def run_dialogue(node_id: str, stage: str, player_state: dict) -> tuple[str, bool]:
    """[서비스] 대화 그래프를 invoke해 (대사, 캐시히트여부) 반환.

    담당: 오케스트레이션 연결 = 김예슬.
    """
    state: DialogueState = {
        "node_id": node_id,
        "stage": stage,
        "player_state": player_state,
    }
    result = await _graph.ainvoke(state)
    return result.get("response", ""), result.get("cache_hit", False)
