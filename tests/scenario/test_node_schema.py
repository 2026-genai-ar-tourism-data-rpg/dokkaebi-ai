# ============================================================
# [v2] 노드 스키마 생성층 테스트 — #30 리뷰 반영분 검증
# 커버: ① 동기→미션 타입 정합(모순 차단) ② spot S7 배제·빈 노드 금지
#       ③ 역사서술 오버라이드 억제·cat 코드 ④ 단서 유도·유일성(단서설계규칙.md)
#       ⑤ NPC 합성(8-B) ⑥ QA 조사 스트리핑 + 기존 앱 계약 정합(유지)
# 구현일: 2026-07-30 | 작성: pjh (node-schema-gen/pjh/v1)
# ============================================================
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.scenario.node_schema import (
    MISSION_TO_STRATEGIES,
    NodeContractError,
    choose_clue_name,
    derive_clue_name,
    enrich_quest,
    infer_motivations,
    link_state_graph,
    reroll_strategy,
    run_qa,
    select_mission_type,
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
    assert listen["choices"][0]["reward_mod"] == {"coupon": 500}
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


def test_clue_is_derived_from_target_requirement():
    # S3: 정답 일부(초성) — "흥선대원군" → ㅎ
    s3 = _stone("n_s3", "조각", "S3_RIDDLE_UNLOCK")
    s3["quiz"] = {"q": "?", "options": ["세종대왕", "흥선대원군"], "answer": 1}
    assert derive_clue_name(s3) == "ㅎ"
    # S2: 요괴 수 — count 5 → 五影
    s2 = _stone("n_s2", "조각", "S2_HUNT_GATHER")
    s2["mission"] = {"type": "HUNT", "count": 5}
    assert derive_clue_name(s2) == "五影"
    # S6: 개수 — 부재 3개 → 三片
    s6 = _stone("n_s6", "조각", "S6_ACCUMULATE")
    s6["mission"] = {"type": "RESTORE_AR", "parts": ["주춧돌", "기둥", "지붕 부재"]}
    assert derive_clue_name(s6) == "三片"
    # S5: 촬영 대상
    s5 = _stone("n_s5", "조각", "S5_PHOTO_PROOF")
    s5["mission"] = {"type": "PHOTO_FIND", "photo_targets": ["현판"]}
    assert derive_clue_name(s5) == "현판"


def test_clue_names_are_unique_within_scenario():
    # 같은 전략·같은 미션 데이터가 반복돼도 시나리오 안에서 이름이 겹치지 않는다.
    stones = [_stone(f"n{i}", f"조각{i}", "S3_RIDDLE_UNLOCK") for i in range(1, 5)]
    finale = _stone("nf", "조각f", "S6_ACCUMULATE", finale=True)
    linked = link_state_graph([*stones, finale])
    clues = [n["clue"] for n in linked if n["clue"]]
    assert len(clues) == len(set(clues)) == 4


def test_clue_is_string_and_links_only_between_main_stones():
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
    n2 = _stone("n2", "글씨조각2", "S3_RIDDLE_UNLOCK")
    finale = _stone("n3", "글씨조각3", "S6_ACCUMULATE", finale=True)

    linked = link_state_graph([n1, food, n2, finale])
    by_id = {node["node_id"]: node for node in linked}

    assert isinstance(by_id["n1"]["clue"], str)
    assert f"clue:{by_id['n1']['clue']}" in by_id["n1"]["grants"]
    assert f"clue:{by_id['n1']['clue']}" in by_id["n2"]["requires"]
    assert by_id["n2"]["requires_mode"] == "soft"
    assert by_id["food"]["grants"] == []
    assert by_id["food"]["requires"] == []


def test_last_nonfinal_also_gets_clue_card_but_finale_does_not_require_it():
    n1 = _stone("n1", "글씨조각1", "S4_PHOTO_TRAIL")
    n2 = _stone("n2", "글씨조각2", "S3_RIDDLE_UNLOCK")
    finale = _stone("n3", "글씨조각3", "S6_ACCUMULATE", finale=True)
    linked = link_state_graph([n1, n2, finale])

    assert linked[1]["clue"] is not None
    assert any(state.startswith("clue:") for state in linked[1]["grants"])
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
    quest = _fixture()
    quest["mission"]["hints"] = ["흥선대원군을 고르거라."]
    node = enrich_quest(quest, _source(content_type_id=28))
    # 생성 시 유출 문자열을 치환하므로 실제 출력은 통과해야 한다.
    qa = run_qa(node, _source(content_type_id=28))
    assert qa["answer_leak"] is False
    assert qa["tone_ok"] is True
    assert qa["contract_ok"] is True


def test_qa_hallucination_tolerates_korean_particles():
    # overview의 명사가 조사만 바뀌어 대사에 나오면 환각이 아니다.
    node = enrich_quest(_fixture(), _source())
    node["npc_dialogue"] = "운현궁에서 한옥 건축의 흔적을 살펴보거라, 허허."
    qa = run_qa(node, _source())
    assert qa["hallucination_flag"] is False


def test_qa_flags_dense_offgrounding_dialogue():
    node = enrich_quest(_fixture(), _source())
    node["npc_dialogue"] = "우주선과 공룡화석과 피라미드보물이 잠들어 있느니라."
    qa = run_qa(node, _source())
    assert qa["hallucination_flag"] is True