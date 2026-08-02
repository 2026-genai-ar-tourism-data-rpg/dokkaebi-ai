# ============================================================
# [v1] 경로 분기 테스트 — 선형 node_sequence → 다이아몬드 트리 (이슈 #24)
# pipeline: AI 백엔드 / 시나리오 (테스트, 오프라인·결정론 — LLM/네트워크 없음)
# 구현(요약): (1) 분기 지점 선택 규칙, (2) 샛길 최근접 픽, (3) attach_branch 다이아몬드 조립,
#            (4) route_tree 무결성·수렴 검증, (5) 두 갈래(main/b1) traverse가 각각 다른 길로
#            갔다가 '공통 재합류 노드'에 도달(분기 route 플레이 1케이스), (6) 샛길은 조각 아님.
#            [#38] (7) 어느 갈래를 골라도 requires 충족(완주 가능), (8) 샛길이 대체 노드의
#            조각·단서를 승계 — link_state_graph(상태) × route_tree(경로) 교차 검증.
#            pytest 없이도 실행: `PYTHONPATH=. python tests/scenario/test_branching.py`
# 구현일: 2026-07-14 (완주 가능성 교차 검증 추가: 2026-08-02) | 작성: kys (route-branching/kys/v1)
# ============================================================
from app.scenario.generator import _build_branch_quest, _build_quest, _plan_nodes
from app.scenario.node_schema import link_state_graph
from app.scenario.route_branching import (
    BRANCH_ID,
    MAIN_ID,
    attach_branch,
    pick_alternate,
    select_branch_point,
    traverse,
    validate_tree,
)


def _spot(nid: str, name: str, lng: float, lat: float) -> dict:
    return {"node_id": nid, "name": name, "map_x": lng, "map_y": lat}


# 본선 5개 관광 노드(대략 일렬)
_ROUTE = [
    _spot("s1", "운현궁", 126.9858, 37.5745),
    _spot("s2", "인사동", 126.9856, 37.5740),
    _spot("s3", "공예박물관", 126.9800, 37.5765),
    _spot("s4", "경복궁", 126.9770, 37.5796),
    _spot("s5", "북촌", 126.9850, 37.5826),
]
# 예비(본선 밖) 후보 — s2에 가까운 alt_near, 먼 alt_far
_ALT_NEAR = _spot("a_near", "샛길가까움", 126.9857, 37.5741)
_ALT_FAR = _spot("a_far", "샛길멀리", 126.9990, 37.5900)


def _main_sequence(route: list[dict]) -> list[dict]:
    """route → 본선 node_sequence(퀘스트 dict). 미션 없이(오프라인) 조립."""
    metas = _plan_nodes(route)
    return [_build_quest(n, i, metas[i], "종로", f"대사{i}") for i, n in enumerate(route)]


def test_select_branch_point_picks_second_spot():
    seq = _main_sequence(_ROUTE)
    # i=1(둘째 관광)부터 탐색, BP·M 둘 다 관광·비피날레여야 함 → 1
    assert select_branch_point(seq) == 1


def test_select_branch_point_none_when_too_short():
    seq = _main_sequence(_ROUTE[:3])          # 노드 3개 → BP,M,R 여유 없음
    assert select_branch_point(seq) is None


def test_pick_alternate_nearest_to_branch():
    seq = _main_sequence(_ROUTE)
    bp_i = 1                                   # BP = s2(인사동)
    alt = pick_alternate(seq, [_ALT_FAR, _ALT_NEAR], bp_i)
    assert alt["node_id"] == "a_near"          # BP에 더 가까운 후보


def test_pick_alternate_none_when_no_reserve():
    seq = _main_sequence(_ROUTE)
    assert pick_alternate(seq, [], 1) is None


def _branched():
    """공용: 본선 + 갈림길 1곳 얹은 (node_sequence, route_tree)."""
    seq = _main_sequence(_ROUTE)
    bp_i = select_branch_point(seq)
    alt_src = pick_alternate(seq, [_ALT_FAR, _ALT_NEAR], bp_i)
    alt_quest = _build_branch_quest(alt_src, len(seq), "종로", "샛길 대사", mission=None)
    seq2, tree = attach_branch(seq, bp_i, alt_quest)
    return seq2, tree, bp_i


def test_attach_branch_makes_valid_diamond():
    seq2, tree, bp_i = _branched()
    validate_tree(tree)                        # 무결성 + 수렴(재합류) 검증 통과해야 함
    bp_id = _ROUTE[bp_i]["node_id"]            # s2
    assert tree["branch_points"] == [bp_id]
    # BP 노드에 선택지 2개(main/b1)
    opts = tree["nodes"][bp_id]["choices"]
    assert [o["choice_id"] for o in opts] == [MAIN_ID, BRANCH_ID]


def test_paths_diverge_then_converge():
    seq2, tree, bp_i = _branched()
    main_path = traverse(tree, {})                         # 기본 = 원래 길
    bp_id = _ROUTE[bp_i]["node_id"]
    alt_path = traverse(tree, {bp_id: BRANCH_ID})          # 샛길 선택
    # 갈래가 실제로 갈라진다: 원래 길엔 M(s3), 샛길엔 A(a_near)
    assert "s3" in main_path and "a_near" not in main_path
    assert "a_near" in alt_path and "s3" not in alt_path
    # 그리고 둘 다 재합류 노드 R(s4) + 피날레 s5에 도달(수렴)
    assert main_path[-1] == "s5" and alt_path[-1] == "s5"
    assert "s4" in main_path and "s4" in alt_path


def test_branch_node_is_not_a_stone():
    seq2, tree, _ = _branched()
    alt = next(q for q in seq2 if q["path_id"] == BRANCH_ID)
    assert alt["stone_no"] is None                          # 조각 번호 없음
    assert alt["fragment_id"] == "종로_branch_b1"
    # 본선 노드는 path_id=main
    assert all(q["path_id"] == MAIN_ID for q in seq2 if q["node_id"].startswith("s"))
    # 본선 조각 회계 불변: 관광 5개 그대로(샛길은 total에 안 낌)
    assert sum(1 for q in seq2 if q["path_id"] == MAIN_ID and q["kind"] == "spot") == 5


def _walk_states(seq: list[dict], tree: dict, choices: dict) -> list[str]:
    """한 갈래를 실제로 밟으며 requires 충족을 검사 → 못 채운 항목 목록(빈 리스트=완주 가능).

    앱의 상태 그래프 소비를 그대로 흉내: 노드에 도착할 때 requires가 인벤토리에 있어야 하고,
    통과하면 grants를 인벤토리에 넣는다.
    """
    by_id = {q["node_id"]: q for q in seq}
    inventory: set[str] = set()
    missing: list[str] = []
    for node_id in traverse(tree, choices):
        node = by_id[node_id]
        for ref in node.get("requires") or []:
            if ref not in inventory:
                missing.append(f"{node['name']}<-{ref}({node.get('requires_mode')})")
        inventory.update(node.get("grants") or [])
    return missing


def test_every_route_is_completable():
    """[회귀 #38] 어느 갈래를 골라도 requires가 항상 충족돼야 한다(완주 가능).

    이전 결함: 샛길 A를 타면 본선 M을 건너뛰는데 M의 조각·단서를 아무도 안 줘서
    피날레 hard requires가 안 열렸다(완주 불가). 트리 모양만 보던 기존 테스트는 못 잡았고,
    link_state_graph(상태 그래프) × route_tree(경로)를 교차 검증해야 잡힌다.
    """
    seq2, tree, bp_i = _branched()
    linked = link_state_graph(seq2)
    bp_id = _ROUTE[bp_i]["node_id"]

    for label, choices in [("본선(main)", {}), ("샛길(b1)", {bp_id: BRANCH_ID})]:
        missing = _walk_states(linked, tree, choices)
        assert not missing, f"{label} 경로 완주 불가 — 미충족: {missing}"


def test_branch_inherits_substituted_stone():
    """[회귀 #38] 샛길 A는 자기가 대체하는 본선 M의 조각·단서를 승계한다(갈래 간 등가)."""
    seq2, tree, bp_i = _branched()
    linked = link_state_graph(seq2)
    by_id = {q["node_id"]: q for q in linked}
    alt, m = by_id["a_near"], by_id["s3"]      # 샛길 A / 그가 대체하는 본선 M

    assert alt["substitutes"] == "s3"
    # 조각·단서가 M과 동일 — 어느 갈래로 가도 같은 조각을 얻는다
    assert alt["fragment_id"] == m["fragment_id"]
    assert alt["stone_no"] == m["stone_no"]
    assert alt["clue"] == m["clue"]
    m_states = {s for s in m["grants"] if s.startswith(("fragment:", "clue:"))}
    assert m_states and m_states <= set(alt["grants"])
    # 분기 전용 조각은 더 이상 남기지 않는다(조각 회계 이중 계상 방지)
    assert "fragment:종로_branch_b1" not in alt["grants"]
    # 피날레 requires는 본선 기준 그대로 — 샛길이 조각 수를 늘리지 않는다
    finale = next(q for q in linked if q.get("is_finale"))
    assert finale["requires"] == [q["fragment_id"] and f"fragment:{q['fragment_id']}"
                                  for q in linked
                                  if q.get("path_id") == MAIN_ID and not q.get("is_finale")]


def test_validate_tree_rejects_nonconverging():
    # 두 갈래가 절대 안 만나는 트리 → 검증 실패해야 함
    bad = {
        "entry_node_id": "x",
        "branch_points": ["x"],
        "nodes": {
            "x": {"next": "p", "choices": [
                {"choice_id": "main", "label": "", "next_node_id": "p"},
                {"choice_id": "b1", "label": "", "next_node_id": "q"},
            ]},
            "p": {"next": None},                # 한쪽 끝
            "q": {"next": None},                # 다른 쪽 끝(안 만남)
        },
    }
    try:
        validate_tree(bad)
    except AssertionError:
        return
    raise AssertionError("비수렴 트리를 통과시킴(검증 결함)")


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all passed")
