# ============================================================
# [v1] 비인기 라벨링 — density_tier (현재 MOCK)
# pipeline: AI 백엔드 / 시나리오 (노드 메타: 인기/비인기)
# 구현(요약): ⚠️ MOCK. 실제는 빅데이터(집중률·중심관광지) EDA로 컷오프 산정(별도 task, 박준형).
#            지금은 좌표/이름 해시로 결정적 임시 라벨 → 앵커+샛길·보상 가중치 자리만.
# 구현일: 2026-06-19 | 작성: kys (node-content/kys/v1)
# 관련: 기획 1-3 적재 우선순위(비인기 라벨링은 별도 워크스트림)
# ============================================================
import hashlib


def density_label(node: dict) -> str:
    """[MOCK] 'popular' | 'low_traffic'. 실제는 LocgoHubTar(중심성)+TatsCnctrRate(집중률)로.

    임시: 이름 해시 기반 결정적 분배(약 1/3 비인기). 실데이터 task에서 교체.
    """
    key = node.get("name") or node.get("node_id") or ""
    h = int(hashlib.sha256(key.encode()).hexdigest()[:4], 16)
    return "low_traffic" if h % 3 == 0 else "popular"


def reward_weight(tier: str) -> float:
    """비인기지 보상 가중치(분산 유도). 실수치는 EDA로 확정."""
    return 1.5 if tier == "low_traffic" else 1.0
