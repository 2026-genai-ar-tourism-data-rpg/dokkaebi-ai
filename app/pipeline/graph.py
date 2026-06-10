# ============================================================
# [v1] LangGraph StateGraph 조립 (baseline 골격)
# pipeline: AI 백엔드 / 오케스트레이션 (전체 그래프 와이어링)
# 구현(요약): 노드 등록 + 조건 엣지(캐시 히트→END / use_rag→retrieve) 연결. 컴파일된 그래프 반환
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from langgraph.graph import END, START, StateGraph

from app.pipeline.nodes.cache import cache_read, cache_write
from app.pipeline.nodes.context_load import context_load
from app.pipeline.nodes.generate import generate
from app.pipeline.nodes.persona_inject import persona_inject
from app.pipeline.nodes.prompt_assemble import prompt_assemble
from app.pipeline.nodes.retrieve import retrieve
from app.pipeline.state import DialogueState


def _route_after_cache(state: DialogueState) -> str:
    """조건 엣지: 대사 캐시 히트면 종료, 미스면 context_load로."""
    return END if state.get("cache_hit") else "context_load"


def _route_after_context(state: DialogueState) -> str:
    """조건 엣지: 옵션 RAG 필요(use_rag)면 retrieve, 아니면 바로 prompt_assemble."""
    return "retrieve" if state.get("use_rag") else "prompt_assemble"


def build_graph():
    """[baseline] NPC 대화 LangGraph 조립 후 컴파일해 반환.

    흐름:
      START → persona_inject → cache_read
          ├─(hit)──────────────────────────────────→ END
          └─(miss)→ context_load
                       ├─(use_rag)→ retrieve → prompt_assemble
                       └─(no)────────────────→ prompt_assemble
                                                   → generate → cache_write → END
    담당: 그래프 설계 = 김예슬 / 각 노드 본문 = 담당자(파일 헤더 참조).
    """
    g = StateGraph(DialogueState)
    g.add_node("persona_inject", persona_inject)
    g.add_node("cache_read", cache_read)
    g.add_node("context_load", context_load)
    g.add_node("retrieve", retrieve)
    g.add_node("prompt_assemble", prompt_assemble)
    g.add_node("generate", generate)
    g.add_node("cache_write", cache_write)

    g.add_edge(START, "persona_inject")
    g.add_edge("persona_inject", "cache_read")
    g.add_conditional_edges(
        "cache_read", _route_after_cache,
        {"context_load": "context_load", END: END},
    )
    g.add_conditional_edges(
        "context_load", _route_after_context,
        {"retrieve": "retrieve", "prompt_assemble": "prompt_assemble"},
    )
    g.add_edge("retrieve", "prompt_assemble")
    g.add_edge("prompt_assemble", "generate")
    g.add_edge("generate", "cache_write")
    g.add_edge("cache_write", END)
    return g.compile()
