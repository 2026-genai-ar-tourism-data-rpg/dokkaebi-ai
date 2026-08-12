# ============================================================
# [v1] 노드: context_load — 그 장소 텍스트 직접 주입(기본 grounding)
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (cache miss 후)
# 구현(요약): 지역 인메모리 캐시에서 node 텍스트 조회 → context 주입. RAG는 기본 off
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from app.pipeline.state import DialogueState
from app.region.memory_cache import get_region_cache


async def context_load(state: DialogueState) -> dict:
    """[노드] 지역 RAM 워킹셋에서 그 장소 텍스트를 가져와 프롬프트 컨텍스트로 직접 주입.

    기본 grounding = 직접 주입(벡터검색 X). use_rag는 기본 False.
    담당: 정찬희(배선) / 지역 캐시 데이터 = 이지선.
    """
    node_id = state.get("node_id", "")
    cache = get_region_cache()
    text = await cache.get_text(node_id)  # 미스 시 cache가 TourAPI 재조회까지 시도
    # TODO(박준형): 텍스트가 컨텍스트 한도 초과/교차검색 필요 시 use_rag=True로 자동 분기하는 로직.
    # 그 로직이 들어오기 전까지는, 호출측이 이미 정한 use_rag를 그대로 보존한다(기본 False) —
    # 여기서 무조건 False로 덮어쓰면 retrieve 노드가 영영 못 탄다(실행 검증 중 발견한 버그, #실행확인 2026-08-12).
    return {"context": text or "", "use_rag": state.get("use_rag", False)}
