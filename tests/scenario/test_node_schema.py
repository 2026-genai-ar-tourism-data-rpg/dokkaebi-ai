from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.scenario.node_schema import (
    NodeContractError,
    choose_clue_name,
    enrich_quest,
    infer_motivations,
    link_state_graph,
    reroll_strategy,
    run_qa,
    select_strategies,
    strategy_is_valid,
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


def test_motivation_mapping_and_keyword_override():
    assert infer_motivations(_source()) == ["M1"]
    assert infer_motivations(_source(overview="유물을 잃어버려 되찾아야 한다")) == ["M8"]
    assert infer_motivations(_source(overview="먹그림자가 장소를 위협한다")) == ["M2"]
    assert infer_motivations(_source(content_type_id=39), is_food=True) == ["M6"]


def test_m4_is_paired_with_playable_motivation():
    assert infer_motivations(_source(content_type_id=32, overview="도심의 자연 공원")) == ["M4", "M1"]


def test_strategy_constraint_and_reroll():
    assert strategy_is_valid("S4_PHOTO_TRAIL", ["M1"])
    assert not strategy_is_valid("S2_HUNT_GATHER", ["M1"])
    assert reroll_strategy("S2_HUNT_GATHER", ["M1"]) == "S4_PHOTO_TRAIL"
    assert select_strategies(["M6"], "HUNT", is_food=True) == ["S7_PATRONIZE"]


def test_finale_s6_is_explicit_structural_exception():
    assert strategy_is_valid("S6_ACCUMULATE", ["M3"], is_finale=True)
    assert select_strategies(["M3"], "DIALOGUE_COLLECT", is_finale=True) == ["S6_ACCUMULATE"]


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


def test_clue_name_is_deterministic_and_strategy_specific():
    assert choose_clue_name("S3_RIDDLE_UNLOCK", "n1") == choose_clue_name("S3_RIDDLE_UNLOCK", "n1")
    assert choose_clue_name("S3_RIDDLE_UNLOCK", "n1") in {"ㄱ", "益", "申時", "三"}


def test_qa_detects_answer_leak_and_tone():
    quest = _fixture()
    quest["mission"]["hints"] = ["흥선대원군을 고르거라."]
    node = enrich_quest(quest, _source(content_type_id=28))
    # 생성 시 유출 문자열을 치환하므로 실제 출력은 통과해야 한다.
    qa = run_qa(node, _source(content_type_id=28))
    assert qa["answer_leak"] is False
    assert qa["tone_ok"] is True
    assert qa["contract_ok"] is True
