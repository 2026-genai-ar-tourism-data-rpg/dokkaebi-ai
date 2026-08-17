# ============================================================
# [v1] 종로 고정 스크립트 테스트
# scenario: 종로 정답지 재생 (MVP)
# 구현(요약): 스크립트 5개 퀘스트(본선 4 + 사이드 1)가 완성되고
#            validate_app_contract를 통과하는지 검증.
#            pytest 없이도 실행: `PYTHONPATH=. python tests/scenario/test_jongno_script.py`
# 구현일: 2026-08-18 | 작성: 정찬희
# ============================================================
from app.scenario.jongno_script import generate_jongno_script
from app.scenario.node_schema import validate_app_contract


def test_jongno_script_structure():
    """정상: 종로 스크립트 구조 검증."""
    scn = generate_jongno_script(region="종로")
    assert scn["region"] == "종로"
    assert scn["stone_total"] == 3
    assert len(scn["node_sequence"]) == 5  # 본선 4 + 사이드 1
    assert scn["node_sequence"][0]["node_id"] == "tour_unhyeongung"
    assert scn["node_sequence"][3]["is_finale"] is True  # 광화문은 피날레
    assert scn["node_sequence"][4]["node_id"] == "side_yisunsin"  # 사이드


def test_jongno_script_quests_pass_contract():
    """정상: 모든 퀘스트가 app 호환 검증을 통과한다."""
    scn = generate_jongno_script(region="종로")
    for quest in scn["node_sequence"]:
        try:
            validate_app_contract(quest)
        except Exception as e:
            raise AssertionError(
                f"quest {quest.get('node_id')} failed validate_app_contract: {e}"
            ) from e


def test_jongno_script_fragment_chain():
    """정상: 조각 체인이 완성되었는가(1 → 2 → 3 → combine)."""
    scn = generate_jongno_script(region="종로")
    quests = scn["node_sequence"]
    # 운현궁: grants stone_1of3
    assert "fragment:종로_stone_1of3" in quests[0]["grants"]
    # 익선동: requires stone_1of3(soft), grants stone_2of3
    assert "clue:申時" in quests[0]["grants"]
    assert "clue:申時" in quests[1]["requires"]
    assert "fragment:종로_stone_2of3" in quests[1]["grants"]
    # 인사동: requires stone_2of3(soft), grants stone_3of3
    assert "clue:ㄱ" in quests[1]["grants"]
    assert "clue:ㄱ" in quests[2]["requires"]
    assert "fragment:종로_stone_3of3" in quests[2]["grants"]
    # 광화문: requires all 3 stones (hard)
    assert "fragment:종로_stone_1of3" in quests[3]["requires"]
    assert "fragment:종로_stone_2of3" in quests[3]["requires"]
    assert "fragment:종로_stone_3of3" in quests[3]["requires"]


def test_jongno_script_npc_personas():
    """정상: 각 노드의 NPC 페르소나가 완성되었는가."""
    scn = generate_jongno_script(region="종로")
    quests = scn["node_sequence"]
    npc_names = [q["npc"]["name"] for q in quests]
    assert "먹 도깨비" in npc_names
    assert "한옥 도깨비" in npc_names
    assert "붓장수 도깨비" in npc_names
    assert "세종대왕" in npc_names
    assert "이순신 장군" in npc_names


def test_jongno_script_quizzes():
    """정상: 본선 노드 1~3에만 퀴즈가 있고, 피날레(4)는 조합식(퀴즈 없음)."""
    scn = generate_jongno_script(region="종로")
    quests = scn["node_sequence"][:4]  # 본선만 (사이드 제외)
    # 1, 2, 3 노드: 퀴즈 있음
    for q in quests[:3]:
        assert q["quiz"] is not None, f"quiz missing for {q['node_id']}"
        assert "question" in q["quiz"]
        assert "options" in q["quiz"]
        assert "answer_idx" in q["quiz"]
    # 4 노드(피날레): 퀴즈 없음, 조합식
    assert quests[3]["quiz"] is None, "finale should not have quiz (combine instead)"
    assert quests[3]["is_finale"] is True


def _run_all() -> int:
    """pytest 없이 직접 실행하는 미니 러너. 실패가 있으면 종료코드 1."""
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys

    sys.exit(_run_all())
