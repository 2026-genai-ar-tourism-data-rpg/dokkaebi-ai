# ============================================================
# [v2] 노드 스키마 생성층 테스트 — #30 리뷰 반영분 검증
# 커버: ① 동기→미션 타입 정합(모순 차단) ② spot S7 배제·빈 노드 금지
#       ③ 역사서술 오버라이드 억제·cat 코드 ④ 단서 유도·유일성(단서설계규칙.md)
#       ⑤ NPC 합성(8-B) ⑥ QA 조사 스트리핑 + 기존 앱 계약 정합(유지)
# 구현일: 2026-07-30 | 작성: pjh (node-schema-gen/pjh/v1)
# ------------------------------------------------------------
# [v3] ④ 단서 = 퀴즈의 귀띔 — 퀴즈 바로 앞 장소만 '<장소> 시험의 귀띔'을 주고 퀴즈가 요구한다.
#      퀴즈가 아니거나(보기 3개 미만 포함) 첫 장소가 퀴즈면 단서 없음.
# 구현일: 2026-09-19 | 작성: ljs (quiz-clue/ljs/v1)
# ============================================================
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.scenario.node_schema import (
    MISSION_TO_STRATEGIES,
    NodeContractError,
    choose_clue_name,
    enrich_quest,
    infer_motivations,
    link_state_graph,
    quiz_clue_name,
    reroll_strategy,
    run_qa,
    select_mission_type,
    select_mission_types_for_course,
    pick_balanced_mission_type,
    app_quest_of,
    select_strategies,
    strategy_is_valid,
    synthesize_npc,
    validate_app_contract,
)


FIXTURE = Path(__file__).parent / "fixtures" / "app_v3_node.json"


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _source(**overrides) -> dict:
    data = {
        "node_id": "tour_unhyeongung",
        "name": "운현궁",
        "content_type_id": 12,
        "cat1": "A02",
        "overview": "운현궁은 조선 후기의 역사적 장소이며 한옥 건축을 볼 수 있다.",
    }
    data.update(overrides)
    return data


def _stone(node_id: str, fragment_id: str, strategy: str, *, finale: bool = False) -> dict:
    return {
        "node_id": node_id,
        "order": 0,
        "name": node_id,
        "kind": "spot",
        "fragment_id": fragment_id,
        "npc_dialogue": "흔적을 살펴보거라, 허허.",
        "is_finale": finale,
        "mission": {
            "type": "DIALOGUE_COLLECT" if finale else "PHOTO_FIND",
            "order": "흔적을 찾아라.",
            "hints": ["주변을 보거라."],
            "photo_targets": ["현판"],
        },
        "quiz": None,
        "objective": None,
        "motivation": ["M3"] if finale else ["M1"],
        "strategy": [strategy],
        "actions": [
            {"a": "goto", "place": node_id},
            {"a": "listen", "slot": "intro+choices", "choices": [{"id": "A"}]},
            {"a": "combine", "items": []} if finale else {"a": "capture", "targets": ["현판"]},
            {"a": "report", "npc": "수호 도깨비"},
        ],
        "hint_ladder": {
            "H1": "주변을 보거라.",
            "H2": "현판을 보거라.",
            "H3": "가까이 살펴보거라.",
            "open_rule": ["fail1|idle60", "idle90", "button"],
        },
        "grants": [] if finale else [f"fragment:{fragment_id}"],
        "requires": [],
        "requires_mode": "none",
        "clue": None,
        "success": ["place_verified"],
    }


# ── ③ 동기 추론 — 카테고리 유지 오버라이드 · 역사서술 억제 · cat 코드 ──


def test_motivation_mapping_and_keyword_override():
    assert infer_motivations(_source()) == ["M1"]
    # 오버라이드는 기본(유적 M1) 동기를 버리지 않고 앞에 얹는다.
    assert infer_motivations(_source(overview="유물을 잃어버려 되찾아야 한다")) == ["M8", "M1"]
    assert infer_motivations(_source(overview="먹그림자가 장소를 위협한다")) == ["M2", "M1"]
    assert infer_motivations(_source(content_type_id=39), is_food=True) == ["M6"]


def test_restored_heritage_narrative_does_not_trigger_threat_or_loss():
    # 한국 문화재 overview의 표준 서술 — 과거 파괴 + 복원 완료 → M2/M8 아님.
    assert infer_motivations(
        _source(overview="임진왜란 때 파괴되었다가 고종 때 중건된 조선의 법궁이다.")
    ) == ["M1"]
    assert infer_motivations(
        _source(overview="전쟁으로 원형을 잃어버렸으나 복원되었다.")
    ) == ["M1"]


def test_nature_uses_cat_code_not_lodging_ctid():
    # ctid 32(숙박)는 자연이 아니다 — 자연은 cat1=A01 코드로 판별.
    assert infer_motivations(_source(cat1="A01", overview="도심의 자연 공원")) == ["M4", "M1"]
    assert "M4" not in infer_motivations(_source(content_type_id=32, cat1="B02", overview="객실을 갖춘 시설"))


def test_market_spot_is_paired_with_playable_motivation():
    # ② 상권 spot: M6 단독이면 S7(식음 전용)뿐 → M1 동반으로 플레이 보장.
    #    실제 상권은 ctid 38(쇼핑)/cat A04로 들어온다.
    motivations = infer_motivations(
        _source(name="광장시장", content_type_id=38, cat1="A04",
                overview="전통 시장으로 먹거리와 상점이 많다.")
    )
    assert motivations[0] == "M6" and "M1" in motivations
    # cat 코드가 아예 없으면 키워드가 보조로 잡는다.
    no_cat = infer_motivations(
        {"name": "광장시장", "content_type_id": 12,
         "overview": "전통 시장으로 먹거리와 상점이 많다."}
    )
    assert no_cat[0] == "M6"


def test_cat_code_beats_overview_keywords():
    # 인사동 실측 오탐 재현 — cat1=A02(인문)면 overview의 "산책/산다"가 자연으로 새지 않는다.
    assert infer_motivations(
        _source(name="인사동", cat1="A02",
                overview="골동품 거리로 힘들지만, 산책하듯이 천천히 둘러보고 고미술을 산다.")
    ) == ["M1"]


# ── 전략 제약 · 리롤 · 미션 타입 선택(①) ─────────────────────────────


def test_strategy_constraint_and_reroll():
    assert strategy_is_valid("S4_PHOTO_TRAIL", ["M1"])
    assert not strategy_is_valid("S2_HUNT_GATHER", ["M1"])
    assert reroll_strategy("S2_HUNT_GATHER", ["M1"]) == "S4_PHOTO_TRAIL"
    assert select_strategies(["M6"], "HUNT", is_food=True) == ["S7_PATRONIZE"]


def test_finale_s6_is_explicit_structural_exception():
    assert strategy_is_valid("S6_ACCUMULATE", ["M3"], is_finale=True)
    assert select_strategies(["M3"], "DIALOGUE_COLLECT", is_finale=True) == ["S6_ACCUMULATE"]


def test_mission_type_respects_motivation_constraints():
    # M1 노드는 어떤 인덱스에서도 사냥/퀴즈 전용 타입을 받지 않는다(모순 차단).
    for index in range(16):
        mtype = select_mission_type(["M1"], index)
        strategies = select_strategies(["M1"], mtype)
        assert strategies, mtype
        assert all(strategy_is_valid(s, ["M1"]) for s in strategies), (mtype, strategies)
    assert select_mission_type(["M1"], 0) != "HUNT"
    assert select_mission_type(["M3"], 3, is_finale=True) == "DIALOGUE_COLLECT"
    assert select_mission_type(["M6"], 0, is_food=True) is None


def test_mission_type_selection_is_diverse_when_allowed():
    # 같은 동기라도 인덱스에 따라 허용 타입 안에서 순환한다.
    types = {select_mission_type(["M1"], i) for i in range(8)}
    assert len(types) >= 2


def test_selected_strategies_never_contradict_mission():
    # v3: 미션 후보 중 유효한 것만 채택 — 무관 전략을 리롤로 끼워 넣지 않는다.
    strategies = select_strategies(["M2", "M1"], "DIALOGUE_FIND")
    assert strategies == ["S1_TALK_GATHER"]           # S3(M7)은 제외, S2를 끼워 넣지 않음
    for mtype, candidates in MISSION_TO_STRATEGIES.items():
        chosen = select_strategies(["M1", "M7"], mtype)
        assert set(chosen) <= set(candidates) or len(chosen) == 1


def test_spot_node_never_gets_s7_and_never_has_empty_play():
    # ② 상권 spot 노드 — S7 배제 + 플레이 원자 보장(공짜 조각 금지).
    source = _source(name="광장시장", node_id="n_gwangjang", content_type_id=38, cat1="A04",
                     overview="전통 시장으로 먹거리와 상점이 많다.")
    motivations = infer_motivations(source)
    mtype = select_mission_type(motivations, 0)
    quest = {
        "order": 0, "node_id": "n_gwangjang", "name": "광장시장", "kind": "spot",
        "fragment_id": "종로_stone_1of3", "npc_dialogue": "허허, 장터로다.",
        "is_finale": False,
        "mission": {"type": mtype, "order": "장터의 기억을 모아라.", "hints": ["둘러보거라."]},
        "quiz": None, "objective": None,
    }
    node = enrich_quest(quest, source, motivations=motivations)
    assert "S7_PATRONIZE" not in node["strategy"]
    play = {"answer", "capture", "tap", "defeat", "follow", "combine"}
    assert any(a["a"] in play for a in node["actions"])


def test_contract_rejects_spot_node_without_play_atoms():
    node = enrich_quest(_fixture(), _source())
    node["actions"] = [a for a in node["actions"] if a["a"] in {"goto", "listen", "report"}]
    with pytest.raises(NodeContractError):
        validate_app_contract(node)


# ── 계약 정합(유지) ─────────────────────────────────────────────────


def test_enriched_node_matches_app_v3_contract():
    node = enrich_quest(_fixture(), _source())
    validate_app_contract(node)

    assert node["motivation"] == ["M1"]
    assert node["strategy"] == ["S4_PHOTO_TRAIL"]
    assert [a["a"] for a in node["actions"]] == [
        "goto",
        "listen",
        "capture",
        "follow",
        "tap",
        "report",
    ]
    assert node["grants"] == ["fragment:글씨조각1"]


def test_choices_are_inside_listen_and_use_action_choice_keys_only():
    node = enrich_quest(_fixture(), _source())
    assert "choices" not in node
    listen = next(action for action in node["actions"] if action["a"] == "listen")
    assert listen["slot"] == "intro+choices"
    assert listen["choices"][0]["flags"] == ["호기심"]
    assert listen["choices"][0]["affinity"] == 1
    assert set().union(*(choice.keys() for choice in listen["choices"])) <= {
        "id",
        "text",
        "flags",
        "affinity",
        "reward_mod",
    }


def test_answer_action_uses_answer_idx():
    quest = _fixture()
    quest["mission"]["type"] = "QUIZ_FIND"
    node = enrich_quest(quest, _source(content_type_id=28))
    answer = next(action for action in node["actions"] if action["a"] == "answer")
    assert answer["quiz"]["answer_idx"] == 1
    assert answer["quiz"]["choices"][1] == "흥선대원군"


def test_hint_ladder_is_flat_app_shape():
    node = enrich_quest(_fixture(), _source())
    ladder = node["hint_ladder"]
    assert isinstance(ladder["H1"], str)
    assert isinstance(ladder["H2"], str)
    assert isinstance(ladder["H3"], str)
    assert ladder["open_rule"] == ["fail1|idle60", "idle90", "button"]


def test_food_node_has_d6_without_unknown_state_or_paths_field():
    quest = {
        "order": 1,
        "node_id": "food_1",
        "name": "익선동 카페",
        "kind": "cafe",
        "fragment_id": None,
        "stone_no": None,
        "npc_dialogue": "차 한 잔 하고 가거라, 허허.",
        "is_finale": False,
        "coupon": {"amount": 500},
        "mission": None,
        "quiz": None,
        "objective": None,
    }
    node = enrich_quest(quest, {"content_type_id": 39, "name": "익선동 카페"})

    assert node["motivation"] == ["M6"]
    assert node["strategy"] == ["S7_PATRONIZE"]
    assert node["fragment_id"] is None
    assert node["grants"] == []
    assert node["clue"] is None
    assert "paths" not in node

    listen = next(a for a in node["actions"] if a["a"] == "listen")
    assert [choice["id"] for choice in listen["choices"]] == ["A", "B"]
    assert "reward_mod" not in listen["choices"][0], "쿠폰 보상은 없앴다(coupon-affinity/ljs/v1)"
    assert next(a for a in node["actions"] if a["a"] == "purchase")["choice_id"] == "A"
    assert next(a for a in node["actions"] if a["a"] == "capture")["choice_id"] == "B"
    assert node["success"] == ["place_verified", "one_of:purchase_verified|free_alternative_done"]


def test_unknown_state_prefix_is_rejected_because_app_treats_it_as_fragment():
    node = enrich_quest(_fixture(), _source())
    node["grants"].append("visit:food_1")
    with pytest.raises(NodeContractError):
        validate_app_contract(node)


# ── ⑤ NPC 합성 (8-B) ────────────────────────────────────────────────


def test_npc_is_synthesized_with_identity_fields():
    node = enrich_quest(_fixture(), _source())
    npc = node["npc"]
    assert npc["name"].endswith("도깨비")
    assert npc["archetype"] == "persona"
    assert npc["motif"]
    assert npc["speech"] == "~니라, 허허"
    assert npc["motivation"] == "M1"
    # report 액션이 합성된 NPC 이름을 쓴다.
    report = next(a for a in node["actions"] if a["a"] == "report")
    assert report["npc"] == npc["name"]
    # 결정적 — 같은 장소는 항상 같은 도깨비.
    assert enrich_quest(_fixture(), _source())["npc"] == npc


def test_npc_finale_is_guardian_and_food_gets_food_motif():
    finale = synthesize_npc(_source(), ["M3"], is_finale=True)
    assert finale["archetype"] == "guardian" and finale["name"] == "수호 도깨비"
    food = synthesize_npc({"content_type_id": 39, "name": "익선동 카페"}, ["M6"], is_food=True)
    assert food["archetype"] == "persona"


# ── ④ 단서 — 수행 조건 유도 + 유일성 (단서설계규칙.md) ─────────────────


def _quiz_stone(node_id: str, fragment_id: str, *, options: int = 4, name: str | None = None) -> dict:
    node = _stone(node_id, fragment_id, "S3_RIDDLE_UNLOCK")
    node["quiz"] = {"q": "?", "options": [f"보기{i}" for i in range(options)], "answer": 1}
    if name:
        node["name"] = name
    return node


def test_quiz_clue_goes_only_to_place_right_before_quiz():
    n1 = _stone("n1", "글씨조각1", "S4_PHOTO_TRAIL")
    n2 = _quiz_stone("n2", "글씨조각2", name="경복궁")
    n3 = _stone("n3", "글씨조각3", "S2_HUNT_GATHER")
    finale = _stone("nf", "글씨조각f", "S6_ACCUMULATE", finale=True)
    by_id = {n["node_id"]: n for n in link_state_graph([n1, n2, n3, finale])}

    assert by_id["n1"]["clue"] == "경복궁 시험의 귀띔"
    assert "clue:경복궁 시험의 귀띔" in by_id["n1"]["grants"]
    assert "clue:경복궁 시험의 귀띔" in by_id["n2"]["requires"]
    assert by_id["n2"]["requires_mode"] == "soft"
    # 퀴즈가 아닌 장소 앞에는 단서가 없다
    assert by_id["n2"]["clue"] is None and by_id["n3"]["clue"] is None
    assert not any(r.startswith("clue:") for r in by_id["n3"]["requires"])
    assert by_id["n3"]["requires_mode"] == "none"


def test_no_quiz_clue_for_first_place_or_quiz_with_too_few_options():
    first = _quiz_stone("q1", "글씨조각1")
    n2 = _stone("n2", "글씨조각2", "S4_PHOTO_TRAIL")
    two_options = _quiz_stone("q3", "글씨조각3", options=2)
    finale = _stone("nf", "글씨조각f", "S6_ACCUMULATE", finale=True)
    linked = link_state_graph([first, n2, two_options, finale])

    assert [n["clue"] for n in linked] == [None, None, None, None]
    assert not any(r.startswith("clue:") for n in linked for r in n["grants"] + n["requires"])


def test_quiz_clue_names_are_unique_within_scenario():
    assert quiz_clue_name({"name": "경복궁"}, {"경복궁 시험의 귀띔"}) == "경복궁 시험의 귀띔·2"
    stones = [_stone("n0", "조각0", "S4_PHOTO_TRAIL")]
    stones += [_quiz_stone(f"n{i}", f"조각{i}", name="같은 이름") for i in range(1, 4)]
    finale = _stone("nf", "조각f", "S6_ACCUMULATE", finale=True)
    clues = [n["clue"] for n in link_state_graph([*stones, finale]) if n["clue"]]
    assert len(clues) == len(set(clues)) == 3


def test_quiz_clue_skips_food_between_giver_and_quiz():
    n1 = _stone("n1", "글씨조각1", "S4_PHOTO_TRAIL")
    food = enrich_quest(
        {
            "node_id": "food",
            "name": "카페",
            "kind": "cafe",
            "fragment_id": None,
            "npc_dialogue": "쉬어가거라, 허허.",
            "is_finale": False,
            "mission": None,
            "quiz": None,
            "objective": None,
        },
        {"content_type_id": 39},
    )
    n2 = _quiz_stone("n2", "글씨조각2")
    finale = _stone("n3", "글씨조각3", "S6_ACCUMULATE", finale=True)

    linked = link_state_graph([n1, food, n2, finale])
    by_id = {node["node_id"]: node for node in linked}

    assert f"clue:{by_id['n1']['clue']}" in by_id["n1"]["grants"]
    assert f"clue:{by_id['n1']['clue']}" in by_id["n2"]["requires"]
    assert by_id["food"]["grants"] == []
    assert by_id["food"]["requires"] == []


def test_last_nonfinal_gets_no_clue_and_finale_does_not_require_one():
    n1 = _stone("n1", "글씨조각1", "S4_PHOTO_TRAIL")
    n2 = _quiz_stone("n2", "글씨조각2")
    finale = _stone("n3", "글씨조각3", "S6_ACCUMULATE", finale=True)
    linked = link_state_graph([n1, n2, finale])

    assert linked[1]["clue"] is None
    assert not any(state.startswith("clue:") for state in linked[2]["requires"])


def test_finale_requires_all_previous_main_fragments_and_combine_items_match():
    n1 = _stone("n1", "글씨조각1", "S4_PHOTO_TRAIL")
    n2 = _stone("n2", "글씨조각2", "S3_RIDDLE_UNLOCK")
    branch = _stone("b1", "분기조각", "S5_PHOTO_PROOF")
    branch["path_id"] = "b1"
    finale = _stone("n3", "글씨조각3", "S6_ACCUMULATE", finale=True)

    linked = link_state_graph([n1, n2, branch, finale])
    final = next(node for node in linked if node["is_finale"])
    assert final["requires"] == ["fragment:글씨조각1", "fragment:글씨조각2"]
    assert final["requires_mode"] == "hard"
    combine = next(action for action in final["actions"] if action["a"] == "combine")
    assert combine["items"] == final["requires"]


def test_pool_fallback_clue_name_is_deterministic():
    assert choose_clue_name("S3_RIDDLE_UNLOCK", "n1") == choose_clue_name("S3_RIDDLE_UNLOCK", "n1")
    assert choose_clue_name("S3_RIDDLE_UNLOCK", "n1") in {"ㄱ", "益", "申時", "三"}


# ── ⑥ QA — 유출 치환 · 어미 · 조사 스트리핑 환각 체크 ─────────────────


def test_qa_detects_answer_leak_and_tone():
    """유출은 '가렸으니 됐다'가 아니라 **다시 쓸 사유**다(계약 변경 20260909-2).

    예전에는 사다리에서 정답을 치환한 뒤 그 결과만 보고 통과로 쳤다 — 그래서
    regen_mission이 한 번도 돌지 않았고, 마스킹 문구("정답과 연결되는 대상와 …")가
    그대로 앱 화면에 나갔다. 이제 사다리는 여전히 정답을 감추되(플레이어 보호),
    판정은 원본 힌트를 보고 True를 낸다(QA 루프가 힌트를 다시 만들게).
    """
    quest = _fixture()
    quest["mission"]["hints"] = ["흥선대원군을 고르거라."]
    node = enrich_quest(quest, _source(content_type_id=28))

    ladder = " ".join(node["hint_ladder"].get(k, "") for k in ("H1", "H2", "H3"))
    assert "흥선대원군" not in ladder                  # 플레이어에게는 여전히 안 보인다
    assert "정답과 연결되는 대상" not in ladder         # 자리표시자도 안 보인다

    qa = run_qa(node, _source(content_type_id=28))
    assert qa["answer_leak"] is True                  # 모델이 쓴 원본에는 정답이 있었다
    assert qa["tone_ok"] is True
    assert qa["contract_ok"] is True


def test_qa_hallucination_tolerates_korean_particles():
    # overview의 명사가 조사만 바뀌어 대사에 나오면 환각이 아니다.
    node = enrich_quest(_fixture(), _source())
    node["npc_dialogue"] = "운현궁에서 한옥 건축의 흔적을 살펴보거라, 허허."
    qa = run_qa(node, _source())
    assert qa["hallucination_flag"] is False


def test_qa_flags_offgrounding_claims():
    """v4: 근거 밖 '주장'(연도·고유명사)이 2개 이상이면 경고."""
    node = enrich_quest(_fixture(), _source())
    node["npc_dialogue"] = "이 운현궁에는 1919년 세워진 첨성대와 석굴암이 있느니라, 허허."
    qa = run_qa(node, _source())
    assert qa["hallucination_flag"] is True
    assert set(qa["unsupported_tokens"]) == {"1919년", "첨성대", "석굴암"}


# ── ⑥-1 환각 판정 v4 골든 픽스처 — 2026-09-04 실 LLM(solar-pro) 점검 대사 ──────
#
# v3 판정은 아래 4건을 전부 환각으로 반려했다(정밀도 0/35). 회귀를 막으려고 실측 대사를
# 그대로 박아 둔다. 대사는 결함보고 20260904 §실측 · §정상 확인된 것에서 옮겼다.

_GOLDEN_DIALOGUES = [
    # (근거 원문, 실제로 나온 대사)
    (
        "보신각은 조선시대 한양 도성의 종을 달아 두었던 종각이다. "
        "새벽과 저녁에 종을 쳐 도성 문을 여닫는 시각을 알렸다.",
        "여기가 바로 도성의 시간을 지키던 보신각터니라. 종소리 울리며 새벽을 알렸다는구먼. 허허.",
    ),
    (
        "민영환 자결터는 을사늑약에 반대하여 자결한 충정공 민영환을 기리는 곳이다.",
        "허허, 이 자리가 바로 민영환 선생이 을사늑약의 치욕을 견디지 못해 "
        "순절로 목숨을 바친 곳이니라. 그 뜻을 헤아리지 않겠느냐?",
    ),
    (
        "탑골공원은 1897년 조성된 서울 최초의 근대식 공원으로, 3·1운동이 시작된 곳이다. "
        "팔각정이 남아 있다.",
        # 표기 차이(대사 '삼일운동' ↔ 원문 '3·1운동')로 걸리면 안 된다.
        "이곳 탑골공원 팔각정은 삼일운동의 함성이 터져 나온 자리니라. 그 이야기를 듣고 싶으냐?",
    ),
    (
        "운현궁은 조선 후기의 역사적 장소이며 한옥 건축을 볼 수 있다. 흥선대원군이 머물던 곳이다.",
        "허허, 운현궁에서 한옥 건축의 흔적을 느껴보겠느냐? "
        "흥선대원군이 머물며 세워진 담장이 예까지 스며들었고, 가벼운 발걸음으로 살펴보거라.",
    ),
]


@pytest.mark.parametrize("overview,dialogue", _GOLDEN_DIALOGUES)
def test_qa_golden_real_dialogues_are_not_hallucinations(overview, dialogue):
    node = enrich_quest(_fixture(), _source(overview=overview))
    node["npc_dialogue"] = dialogue
    qa = run_qa(node, _source(overview=overview))
    assert qa["hallucination_flag"] is False, qa["unsupported_tokens"]
    assert qa["tone_ok"] is True


def test_qa_stopword_survives_particle_stripping():
    """v3 버그: 스톱워드를 조사 제거 '전에만' 걸러 '도깨비로'가 어간 '도깨비'로 되살아났다."""
    node = enrich_quest(_fixture(), _source())
    node["npc_dialogue"] = "도깨비로 살아온 세월이 길구나, 허허."
    qa = run_qa(node, _source())
    assert "도깨비" not in qa["unsupported_tokens"]


# ── [v5] 코스 단위 골고루 배정 ──────────────────────────────────────

def _course_metas(n: int, food_at: tuple[int, ...] = ()) -> list[dict]:
    last = max(i for i in range(n) if i not in food_at)
    metas, sn = [], 0
    for i in range(n):
        if i in food_at:
            metas.append({"is_food": True, "is_finale": False, "stone_index": None})
        else:
            metas.append({"is_food": False, "is_finale": i == last, "stone_index": sn})
            sn += 1
    return metas


def _quests(types, mvs, metas):
    return [None if t is None else app_quest_of(t, mv, is_finale=m["is_finale"])
            for t, mv, m in zip(types, mvs, metas)]


def test_course_assignment_alternates_app_quests_and_never_repeats_consecutively():
    # M1만 있는 유적 코스 — 예전엔 2·3번째가 연속 도깨비불. 이제 도깨비불/빛 순서가 번갈아 온다.
    mvs = [["M1"]] * 5
    metas = _course_metas(5)
    types = select_mission_types_for_course(mvs, metas)
    quests = _quests(types, mvs, metas)
    assert types[-1] == "DIALOGUE_COLLECT"
    body = quests[:-1]
    assert all(a != b for a, b in zip(body, body[1:])), body
    assert body.count("fire") == 2 and body.count("gather") == 2
    # 같은 퀘스트 묶음 안에서도 미션 타입(지령 문구)은 돌아간다
    assert len({t for t, q in zip(types, quests) if q == "fire"}) == 2
    assert len({t for t, q in zip(types, quests) if q == "gather"}) >= 2


def test_course_assignment_prefers_least_used_quest_so_quiz_and_hunt_show_up_early():
    mvs = [["M2", "M1"], ["M1"], ["M1"], ["M1", "M7"], ["M1"]]
    metas = _course_metas(5)
    types = select_mission_types_for_course(mvs, metas)
    quests = _quests(types, mvs, metas)[:-1]
    assert quests[0] == "hunt"                    # M2가 허용한 사냥은 첫 자리에서 바로
    assert "quiz" in quests                       # M7 노드는 덜 쓴 퀴즈를 받는다(예전엔 7번째여야 나왔다)
    assert len(set(quests)) == 4


def test_course_assignment_keeps_motivation_constraints_and_food_finale_rules():
    mvs = [["M1"], ["M6"], ["M3"], ["M1", "M9"], ["M7"], ["M1"]]
    metas = _course_metas(6, food_at=(1,))
    types = select_mission_types_for_course(mvs, metas)
    assert types[1] is None and types[-1] == "DIALOGUE_COLLECT"
    for t, mv, m in zip(types, mvs, metas):
        if t is None or m["is_finale"]:
            continue
        strategies = select_strategies(mv, t)
        assert strategies and all(strategy_is_valid(s, mv) for s in strategies), (t, mv)
    assert app_quest_of(types[2], ["M3"]) == "fire"    # M3만 = 도깨비불뿐(제약표) — 이웃이 피한다
    assert app_quest_of(types[3], ["M1", "M9"]) != "fire"
    assert app_quest_of(types[4], ["M7"]) == "quiz"


def test_branch_pick_avoids_both_neighbours_when_possible():
    from collections import Counter
    t = pick_balanced_mission_type(["M1"], counts=Counter({"fire": 1, "gather": 1}),
                                   prev_quest="fire", next_quest="fire", stone_index=1)
    assert app_quest_of(t, ["M1"]) == "gather"
    t = pick_balanced_mission_type(["M1"], counts=Counter({"fire": 1, "gather": 2}),
                                   prev_quest="gather", next_quest="gather", stone_index=1)
    assert app_quest_of(t, ["M1"]) == "fire"

