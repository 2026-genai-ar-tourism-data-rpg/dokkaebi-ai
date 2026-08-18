# ============================================================
# [v2] 종로 고정 스크립트 테스트 — PDF §3 정답지 기준 (전면 재작성)
# scenario: 종로 정답지 재생 (MVP)
# 구현(요약): 프롤로그+5개 조각 노드+최종노드(7개)가 완성되고
#            validate_app_contract를 통과하는지 검증.
#            pytest 없이도 실행: `PYTHONPATH=. python tests/scenario/test_jongno_script.py`
# 구현일: 2026-08-18 | 작성: 정찬희
# ============================================================
from app.scenario.jongno_script import generate_jongno_script
from app.scenario.node_schema import validate_app_contract


def test_jongno_script_structure():
    """정상: 종로 스크립트 구조 검증(프롤로그+5조각+피날레=7개)."""
    scn = generate_jongno_script(region="종로")
    assert scn["region"] == "종로"
    assert scn["stone_total"] == 5
    assert len(scn["node_sequence"]) == 7
    assert scn["node_sequence"][0]["node_id"] == "tour_anguk"       # 프롤로그
    assert scn["node_sequence"][1]["node_id"] == "tour_unhyeongung"
    assert scn["node_sequence"][6]["node_id"] == "tour_gwanghwamun"
    assert scn["node_sequence"][6]["is_finale"] is True


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
    """정상: 조각 체인(1~5)과 단서 체인(처마3보→溫茶→三墨→손의결→글빛五序)이 이어진다."""
    scn = generate_jongno_script(region="종로")
    quests = scn["node_sequence"]
    prologue, n1, n2, n3, n4, n5, finale = quests

    assert "clue:처마3보" in prologue["grants"]

    assert "clue:처마3보" in n1["requires"]
    assert "fragment:종로_stone_1of5" in n1["grants"]
    assert "clue:溫茶" in n1["grants"]

    assert "clue:溫茶" in n2["requires"]
    assert "fragment:종로_stone_2of5" in n2["grants"]
    assert "clue:三墨" in n2["grants"]

    assert "clue:三墨" in n3["requires"]
    assert "fragment:종로_stone_3of5" in n3["grants"]
    assert "clue:손의결" in n3["grants"]

    assert "clue:손의결" in n4["requires"]
    assert "fragment:종로_stone_4of5" in n4["grants"]
    assert "clue:처마매듭" in n4["grants"]

    assert "clue:처마매듭" in n5["requires"]
    assert "fragment:종로_stone_5of5" in n5["grants"]
    assert "clue:글빛五序" in n5["grants"]

    for i in range(1, 6):
        assert f"fragment:종로_stone_{i}of5" in finale["requires"]


def test_jongno_script_final_order():
    """정상: 최종노드의 배치 정답 순서(글빛 五序)가 먹빛→온기→붓끝→손결→처마빛."""
    scn = generate_jongno_script(region="종로")
    finale = scn["node_sequence"][6]
    assert finale["final_order"] == [
        "종로_stone_1of5", "종로_stone_2of5", "종로_stone_3of5",
        "종로_stone_4of5", "종로_stone_5of5",
    ]
    assert finale["final_order_labels"] == ["먹빛", "온기", "붓끝", "손결", "처마빛"]


def test_jongno_script_npc_personas():
    """정상: 각 노드의 NPC 페르소나가 PDF와 일치한다."""
    scn = generate_jongno_script(region="종로")
    npc_names = [q["npc"]["name"] for q in scn["node_sequence"]]
    assert npc_names == [
        "초롱 도깨비", "먹 도깨비", "온기 도깨비", "붓장수 도깨비",
        "손끝 도깨비", "처마 도깨비", "글빛 수호 도깨비",
    ]


def test_jongno_script_quizzes():
    """정상: 퀴즈는 운현궁(1)·인사동길(3)에만 있고 나머지는 없다(PDF 그대로)."""
    scn = generate_jongno_script(region="종로")
    quests = scn["node_sequence"]
    has_quiz = {q["node_id"] for q in quests if q.get("quiz")}
    assert has_quiz == {"tour_unhyeongung", "tour_insadong"}


def test_jongno_script_endings():
    """정상: 최종노드에 굿/노멀 엔딩이 모두 있고, 굿엔딩만 노드별 정원아이템 5종을 지급한다."""
    scn = generate_jongno_script(region="종로")
    finale = scn["node_sequence"][6]
    endings = finale["endings"]
    assert set(endings.keys()) == {"A", "B"}
    assert len(endings["A"]["rewards"]["garden_items_per_node"]) == 5
    assert endings["B"]["rewards"]["garden_items_per_node"] == []
    # 칭호는 두 엔딩 모두 동일(PDF 그대로)
    assert endings["A"]["rewards"]["title"] == endings["B"]["rewards"]["title"] == "종로의 글빛 복원자"


def test_jongno_script_garden_rewards():
    """정상: 조각 5개 노드 전부에 정원 보상 아이템이 있다."""
    scn = generate_jongno_script(region="종로")
    fragment_quests = [q for q in scn["node_sequence"] if q.get("fragment_id")]
    assert len(fragment_quests) == 5
    for q in fragment_quests:
        assert "garden_reward" in q and q["garden_reward"].get("item")


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
