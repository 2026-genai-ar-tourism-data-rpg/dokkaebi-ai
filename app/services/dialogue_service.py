# ============================================================
# [v1] 대화 서비스 — 그래프 invoke 래핑
# pipeline: AI 백엔드 / 서빙↔오케스트레이션 연결
# 구현(요약): 컴파일된 LangGraph 1회 빌드 후 ainvoke로 실행, 응답 추출
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ------------------------------------------------------------
# [v2] 사용자 발화를 state.query로 끌어올린다.
# 구현(요약): 서버는 자유 발화를 player_state={"user_input": …}에 담아 보낸다.
#            프롬프트에는 발화 자리(query)가 따로 있는데 아무도 채우지 않아,
#            player_state를 dict째 찍던 시절엔 우연히 보이다가 사람 말 변환(v2) 이후
#            통째로 사라졌다. 여기서 명시적으로 옮긴다 — 우연이 아니라 계약으로.
# 구현일: 2026-08-19 | 작성: kys (dialogue-rework/kys/v1)
# ============================================================
from app.core.logger import get_logger
from app.pipeline.graph import build_graph
from app.pipeline.state import DialogueState

logger = get_logger(__name__)

# 컴파일된 그래프는 1회만 빌드(stateless) — 호출마다 state만 주입
_graph = build_graph()


# 서버가 자유 발화를 실어 보내는 키(계약). 앞에 있는 것부터 채택한다.
_UTTERANCE_KEYS = ("user_input", "utterance", "query")


def _utterance(player_state: dict | None) -> str:
    """진행상황 dict에 섞여 들어온 사용자 발화를 꺼낸다(없으면 빈 문자열)."""
    for key in _UTTERANCE_KEYS:
        text = (player_state or {}).get(key)
        if isinstance(text, str) and text.strip():
            return text.strip()
    return ""


async def run_dialogue(
    node_id: str, stage: str, player_state: dict, *, node_name: str = "",
    region_id: str = "", qa_feedback: str = "",
) -> tuple[str, bool]:
    """[서비스] 대화 그래프를 invoke해 (대사, 캐시히트여부) 반환.

    qa_feedback: A1 QA 루프가 반려한 이유(있으면 캐시 우회 + 프롬프트에 재작성 지시).

    담당: 오케스트레이션 연결 = 김예슬.
    """
    state: DialogueState = {
        "node_id": node_id,
        "node_name": node_name,
        "region_id": region_id,
        "stage": stage,
        "player_state": player_state,
        "query": _utterance(player_state),
        "qa_feedback": qa_feedback,
    }
    result = await _graph.ainvoke(state)
    return result.get("response", ""), result.get("cache_hit", False)
