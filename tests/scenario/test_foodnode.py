# ============================================================
# [v1] 식음노드 기억석 오인 방지 테스트 — _plan_nodes / _build_quest 단위 검증
# pipeline: AI 백엔드 / 시나리오 (테스트)
# 구현(요약): route에 kind=food/cafe가 섞여도 (1) 조각 번호·total은 관광 노드만,
#            (2) 식음노드는 fragment_id=None·미션 None, (3) 피날레=마지막 관광 노드,
#            (4) order는 방문 순서(식음 포함)임을 plain assert로 검증.
#            pytest 없이도 실행: `PYTHONPATH=. python tests/scenario/test_foodnode.py`
# 구현일: 2026-07-05 | 작성: kys+pjh (quest-foodnode/kys-pjh/v1)
# ============================================================
from app.scenario.generator import (
    _build_quest,
    _is_food,
    _plan_nodes,
)


def _spot(node_id: str, name: str) -> dict:
    """관광(기억석) 노드 픽스처."""
    return {"node_id": node_id, "name": name, "map_x": 126.99, "map_y": 37.57}


def _food(node_id: str, name: str, kind: str = "food") -> dict:
    """식음 삽입 노드 픽스처(정찬희 hook interleave_food 산출 형태)."""
    return {"node_id": node_id, "name": name, "kind": kind, "band": 2,
            "map_x": 126.99, "map_y": 37.57, "coupon": {"to_kind": "food", "amount": 500}}


# route: 관광-관광-식음-관광(피날레) — 식음이 중간에 낀 전형적 케이스
_ROUTE = [_spot("s1", "경복궁"), _spot("s2", "광화문"),
          _food("f1", "광장시장 빈대떡"), _spot("s3", "북촌")]


def test_is_food_marker():
    assert _is_food(_food("f", "x")) is True
    assert _is_food(_food("c", "x", kind="cafe")) is True
    assert _is_food(_spot("s", "x")) is False


def test_stone_total_excludes_food():
    metas = _plan_nodes(_ROUTE)
    # 관광 3 + 식음 1 → total(조각)은 3이어야 함
    assert all(m["stone_total"] == 3 for m in metas)
    stone_metas = [m for m in metas if not m["is_food"]]
    assert len(stone_metas) == 3
    assert [m["stone_no"] for m in stone_metas] == [1, 2, 3]


def test_food_meta_has_no_stone_number():
    metas = _plan_nodes(_ROUTE)
    food_meta = metas[2]           # f1
    assert food_meta["is_food"] is True
    assert food_meta["stone_no"] is None
    assert food_meta["stone_index"] is None
    assert food_meta["is_finale"] is False


def test_finale_is_last_spot_not_food():
    metas = _plan_nodes(_ROUTE)
    # 피날레는 마지막 '관광' 노드(index 3)만. 식음노드는 절대 피날레 아님.
    assert [m["is_finale"] for m in metas] == [False, False, False, True]


def test_finale_when_food_is_physically_last():
    # 식음이 route 맨 뒤에 붙어도 피날레는 마지막 관광 노드여야 함
    route = [_spot("s1", "a"), _spot("s2", "b"), _food("f1", "c")]
    metas = _plan_nodes(route)
    assert metas[1]["is_finale"] is True     # s2 = 마지막 관광
    assert metas[2]["is_finale"] is False    # f1 = 식음


def test_build_quest_food_has_no_fragment():
    metas = _plan_nodes(_ROUTE)
    q = _build_quest(_ROUTE[2], 2, metas[2], "종로", "요기하고 가거라", mission=None)
    assert q["fragment_id"] is None          # ★ 기억석 조각 아님
    assert q["kind"] == "food"
    assert q["mission"] is None
    assert q["is_finale"] is False
    assert q["coupon"] == {"to_kind": "food", "amount": 500}
    assert q["order"] == 2                    # 방문 순서(식음 포함)는 보존


def test_build_quest_spot_fragment_uses_stone_count():
    metas = _plan_nodes(_ROUTE)
    # 마지막 관광 노드(route index 3, 3번째 조각) → stone_3of3, 피날레
    q = _build_quest(_ROUTE[3], 3, metas[3], "종로", "마지막 조각!", mission=None)
    assert q["fragment_id"] == "종로_stone_3of3"   # total은 식음 제외 3
    assert q["stone_no"] == 3
    assert q["is_finale"] is True
    assert q["kind"] == "spot"
    assert q["order"] == 3


def test_no_food_matches_legacy_behavior():
    # 식음 0개면 기존과 동일: 조각수=노드수, 마지막이 피날레
    route = [_spot("s1", "a"), _spot("s2", "b")]
    metas = _plan_nodes(route)
    assert all(m["stone_total"] == 2 for m in metas)
    q0 = _build_quest(route[0], 0, metas[0], "종로", "d0")
    q1 = _build_quest(route[1], 1, metas[1], "종로", "d1")
    assert q0["fragment_id"] == "종로_stone_1of2"
    assert q1["fragment_id"] == "종로_stone_2of2"
    assert q1["is_finale"] is True


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
            print(f"ok  {_name}")
    print("all passed")
