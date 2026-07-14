# ============================================================
# [v1] 경로 분기 seam — node_sequence 선형 → 트리(다이아몬드 재합류)
# pipeline: AI 백엔드 / 시나리오 (동선 위에 route 분기 얹기 — 이슈 #24)
# 구현(요약): 선형 route에 '갈림길' 1곳을 얹어 두 갈래(원래 길 / 샛길)로 나눴다가
#            한 노드 뒤에서 다시 합류(diamond). 노드 수 선형 유지·조합폭발 없음.
#            결정: eager(생성시 트리 확정, 유계) — 근거는 docs/route-branching.md.
#            순수 함수라 LLM/네트워크 없이 단위 테스트 가능(오프라인 결정론).
# 구현일: 2026-07-14 | 작성: kys (route-branching/kys/v1) · 상위 .github#5
# ============================================================
from app.core.logger import get_logger
from app.tourapi.client import haversine_m

logger = get_logger(__name__)

BRANCH_ID = "b1"          # MVP: 갈림길 1곳, 샛길 갈래 id
MAIN_ID = "main"          # 원래(직진) 갈래 id


def select_branch_point(node_sequence: list[dict]) -> int | None:
    """다이아몬드 갈림길을 얹을 '분기 노드' index를 고른다(없으면 None).

    조건: BP(i)·M(i+1)이 관광(spot)·비피날레여야 하고, 재합류 지점 R(i+2)이 존재해야 함.
    (R은 피날레여도 됨 — 두 갈래가 피날레에서 합류하는 다이아몬드.)
    맨 앞(i=0)은 피해 두 번째 관광 노드부터 탐색 → 도입부는 공통 경험 보장.
    """
    n = len(node_sequence)
    if n < 4:                          # BP,M,R + 최소 1노드는 있어야 의미 있음
        return None
    for i in range(1, n - 2):
        bp, m = node_sequence[i], node_sequence[i + 1]
        if bp.get("kind") == "spot" and not bp.get("is_finale") \
           and m.get("kind") == "spot" and not m.get("is_finale"):
            return i
    return None


def pick_alternate(node_sequence: list[dict], reserve: list[dict], bp_index: int) -> dict | None:
    """분기 노드(BP)에서 가장 가까운 '샛길 후보'를 예비 노드에서 고른다(없으면 None).

    reserve = 본선에 안 쓰인 관광 후보. 좌표 있는 것만. BP 좌표 결측이면 첫 후보.
    """
    cand = [n for n in (reserve or []) if n.get("map_x") is not None and n.get("map_y") is not None]
    if not cand:
        return None
    bp = node_sequence[bp_index]
    bx, by = bp.get("map_x"), bp.get("map_y")
    if bx is None or by is None:
        return cand[0]
    return min(cand, key=lambda n: haversine_m(by, bx, n["map_y"], n["map_x"]))


def attach_branch(
    node_sequence: list[dict], bp_index: int, alt_quest: dict, *,
    prompt: str | None = None, main_label: str | None = None, alt_label: str | None = None,
) -> tuple[list[dict], dict]:
    """선형 node_sequence(본선) + 샛길 노드(alt_quest) → 다이아몬드 트리로 조립.

    구조:  … → BP ─┬─ (원래 길) M ─┐
                    └─ (샛길)   A ─┴─ R → … (재합류)
    - BP에 branch{prompt, options[main→M, b1→A]} 부착(앱이 선택지 렌더).
    - route_tree(edges: node_id→{next, choices?})와 확장 node_sequence 반환.
    - 모든 본선 노드에 path_id='main', 샛길 노드에 path_id='b1' 표기(순서는 트리가 정의).
    """
    seq = [dict(q) for q in node_sequence]
    for q in seq:
        q.setdefault("path_id", MAIN_ID)
    bp, m, r = seq[bp_index], seq[bp_index + 1], seq[bp_index + 2]

    alt = dict(alt_quest)
    alt["path_id"] = BRANCH_ID
    alt.setdefault("order", len(seq))

    prompt = prompt or "갈림길이로다. 어느 길로 가려느냐?"
    main_label = main_label or f"본래 길 — 「{m.get('name', '앞')}」 쪽으로 간다"
    alt_label = alt_label or f"새어 나온 혼불을 따라 「{alt.get('name', '샛길')}」로 샌다"
    options = [
        {"choice_id": MAIN_ID, "label": main_label, "next_node_id": m["node_id"]},
        {"choice_id": BRANCH_ID, "label": alt_label, "next_node_id": alt["node_id"]},
    ]
    bp["branch"] = {"prompt": prompt, "options": options}

    # 트리 간선: 본선은 선형 next, BP는 choices(+기본 next=M), 샛길 A는 R로 재합류.
    nodes_tree: dict[str, dict] = {}
    for idx, q in enumerate(seq):
        nodes_tree[q["node_id"]] = {"next": seq[idx + 1]["node_id"] if idx + 1 < len(seq) else None}
    nodes_tree[bp["node_id"]] = {"next": m["node_id"], "choices": options}
    nodes_tree[alt["node_id"]] = {"next": r["node_id"]}

    seq2 = seq + [alt]
    route_tree = {
        "entry_node_id": seq2[0]["node_id"],
        "branch_points": [bp["node_id"]],
        "nodes": nodes_tree,
    }
    logger.info("route 분기 얹음: BP=%s → [main:%s | b1:%s] ⇒ 재합류 %s",
                bp["node_id"], m["node_id"], alt["node_id"], r["node_id"])
    return seq2, route_tree


def _follow(nodes_tree: dict, start: str | None) -> list[str]:
    """start에서 기본 next만 따라 끝까지 — 갈래 수렴 확인용(선택은 무시)."""
    path, seen, cur = [], set(), start
    while cur is not None and cur not in seen:
        seen.add(cur)
        path.append(cur)
        cur = nodes_tree.get(cur, {}).get("next")
    return path


def traverse(route_tree: dict, choices: dict | None = None) -> list[str]:
    """선택(choices: {branch_point_id: choice_id})을 반영해 실제 밟는 노드 경로를 낸다.

    분기 노드에서 choices에 지정이 있으면 그 갈래로, 없으면 기본(main)으로 진행.
    사이클/누락은 방어(seen)해 항상 종료 → '분기 route 플레이' 1케이스 검증에 사용.
    """
    choices = choices or {}
    nodes = route_tree["nodes"]
    path, seen, cur = [], set(), route_tree["entry_node_id"]
    while cur is not None and cur not in seen:
        seen.add(cur)
        path.append(cur)
        edge = nodes.get(cur, {})
        opts = edge.get("choices")
        if opts:
            pick = choices.get(cur)
            nxt = next((o["next_node_id"] for o in opts if o["choice_id"] == pick), None)
            cur = nxt if nxt is not None else edge.get("next")
        else:
            cur = edge.get("next")
    return path


def validate_tree(route_tree: dict) -> None:
    """route_tree 무결성 검증(실패 시 AssertionError). 생성 직후·테스트에서 호출.

    (1) entry 존재, (2) 모든 next/choice 타깃이 노드에 존재, (3) 자기참조 없음,
    (4) 각 분기의 두 갈래가 결국 한 노드로 재합류(수렴)한다.
    """
    nodes = route_tree["nodes"]
    entry = route_tree["entry_node_id"]
    assert entry in nodes, f"entry {entry} 없음"
    for nid, edge in nodes.items():
        nxt = edge.get("next")
        if nxt is not None:
            assert nxt in nodes, f"next 타깃 {nxt} 없음"
            assert nxt != nid, f"자기참조 next: {nid}"
        for opt in edge.get("choices", []):
            t = opt["next_node_id"]
            assert t in nodes, f"choice 타깃 {t} 없음"
            assert t != nid, f"자기참조 choice: {nid}"
    for bp in route_tree.get("branch_points", []):
        legs = [o["next_node_id"] for o in nodes[bp].get("choices", [])]
        assert len(legs) >= 2, f"분기 {bp} 갈래가 2개 미만"
        common = set.intersection(*[set(_follow(nodes, s)) for s in legs])
        assert common, f"분기 {bp}의 갈래가 재합류하지 않음(수렴 실패)"
