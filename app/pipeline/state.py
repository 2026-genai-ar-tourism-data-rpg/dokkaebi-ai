# ============================================================
# [v1] LangGraph 대화 상태(State) 스키마
# pipeline: AI 백엔드 / 오케스트레이션 (노드 간 전달되는 단일 state 객체)
# 구현(요약): DialogueState TypedDict 정의 (아키텍처 3-2 기준)
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from typing import TypedDict


class DialogueState(TypedDict, total=False):
    """NPC 대화 파이프라인 상태. 그래프의 모든 노드가 이 dict를 읽고 일부를 갱신해 반환."""

    node_id: str          # 장소 노드 ID
    stage: str            # 등장 | 의뢰 | 힌트 | 완료
    player_state: dict    # 진행도, 보유 기억석 조각, 이전 대화 요약(멀티턴)
    persona: dict         # 아키타입·모티프·말투 (이지선 시드)
    context: str          # 기본 grounding: 지역 RAM에서 직접 주입한 그 장소 텍스트
    use_rag: bool         # 옵션 RAG 분기 플래그 (대형 텍스트/교차검색)
    retrieved: list       # (옵션 RAG 시) 인메모리 검색 청크
    confidence: float     # (옵션 RAG 시) 재검색 분기 기준
    prompt: str           # 조립된 최종 프롬프트
    response: str         # NPC 대사 / 힌트 (최종 출력)
    cache_key: str        # 대사 캐시 키
    cache_hit: bool       # 캐시 히트 여부 (히트 시 LLM 스킵)
