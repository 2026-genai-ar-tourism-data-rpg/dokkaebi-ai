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
# ------------------------------------------------------------
# [v3] npc(앱 표시 정체성)를 그래프로 넘긴다 — 대사/앱 이름 불일치 차단(persona_inject v3).
# 구현일: 2026-09-09 | 작성: pjh (agent-qa/pjh/v1)
# ------------------------------------------------------------
# [v4] 운영 로그 — 그래프 진입/종료와 캐시 여부를 남긴다.
# 구현(요약): 이 파일에 로그가 0줄이라 대사가 캐시에서 온 건지 LLM이 만든 건지,
#            자유 발화가 프롬프트에 실렸는지를 로그로 확인할 수 없었다.
# 구현일: 2026-09-12 | 작성: kys (ops-logging/kys/v1)
# ============================================================
import time

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
    region_id: str = "", qa_feedback: str = "", npc: dict | None = None,
) -> tuple[str, bool]:
    """[서비스] 대화 그래프를 invoke해 (대사, 캐시히트여부) 반환.

    qa_feedback: A1 QA 루프가 반려한 이유(있으면 캐시 우회 + 프롬프트에 재작성 지시).
    npc: 앱에 표시되는 NPC 정체성(synthesize_npc). 주면 대사도 같은 도깨비를 쓴다.

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
        "npc": npc or {},
    }
    utterance = state["query"]
    logger.info(
        "대화그래프 시작: node=%s stage=%s 발화=%s%s",
        node_id, stage,
        f"'{utterance[:30]}'" if utterance else "없음",
        " (QA재작성)" if qa_feedback else "",
    )
    t0 = time.perf_counter()
    result = await _graph.ainvoke(state)
    text = result.get("response", "")
    hit = result.get("cache_hit", False)
    if not text:
        # 빈 대사는 앱에서 말풍선이 비어 보이는 결함으로 이어진다 — 조용히 넘기지 않는다.
        logger.warning("대화그래프 결과가 빈 문자열: node=%s stage=%s", node_id, stage)
    logger.info(
        "대화그래프 종료: %s %d자 (%.0fms)",
        "캐시히트" if hit else "LLM생성", len(text), (time.perf_counter() - t0) * 1000,
    )
    return text, hit
