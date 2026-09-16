"""생성 코스의 엔딩 계약과 보상 소유권 회귀 테스트."""

import asyncio
from unittest.mock import AsyncMock, patch

from app.config import get_settings
from app.scenario.ending import attach_endings
from app.scenario.generator import generate_basic_scenario
from app.scenario.node_schema import _action_quiz, _free_path_quiz, build_choices, validate_app_contract
from app.scenario.request import WishItem


def test_generated_finale_has_local_endings_and_choice_action():
    sequence = [
        {"name": "광화문광장", "is_finale": False, "actions": []},
        {"name": "하회마을", "is_finale": True, "actions": [{"a": "report", "npc": "수호 도깨비"}]},
    ]
    attach_endings(sequence, "안동시")
    finale = sequence[-1]
    assert set(finale["endings"]) == {"A", "B"}
    assert {v["ending"] for v in finale["endings"].values()} == {"굿 엔딩", "노멀 엔딩"}
    assert all("안동시" in " ".join(v["npc_dialogue"]) for v in finale["endings"].values())
    assert "종로" not in str(finale["endings"])
    assert finale["endings"]["A"]["rewards"]["title"] == "안동시의 기억 복원자"
    assert finale["endings"]["B"]["rewards"]["garden_item_final"] == "안동시 기억석"
    assert finale["actions"][-2]["slot"] == "ending_choice"
    assert [c["id"] for c in finale["actions"][-2]["choices"]] == ["A", "B"]
    attach_endings(sequence, "안동시")
    assert sum(a.get("slot") == "ending_choice" for a in finale["actions"]) == 1


def test_server_owned_experience_is_not_emitted_by_generated_actions():
    quiz = _action_quiz({"name": "장소", "quiz": {"options": ["맞음", "틀림"], "answer": 0}})
    assert quiz["correct"] == {"coupon": get_settings().scenario_quiz_coupon}
    assert "exp" not in _free_path_quiz("카페")["correct"]
    assert build_choices({}, is_food=False)[1]["reward_mod"] == {
        "coupon": get_settings().scenario_choice_coupon
    }


def test_generated_scenario_exposes_endings_on_its_finale():
    with patch("app.scenario.generator._tour.location_based_list", new=AsyncMock(return_value=[])):
        scenario = asyncio.run(generate_basic_scenario(
            128.73, 36.57, region="안동시", radius_m=100, count=1,
            with_dialogue=False, with_content=False, no_meals=True,
            wishlist=[WishItem(content_id="test_hahoe", name="하회마을", lat=36.57, lng=128.73)],
        ))
    finale = scenario["node_sequence"][-1]
    assert finale["is_finale"] is True
    validate_app_contract(finale)
    assert finale["endings"]["A"]["rewards"]["title"] == "안동시의 기억 복원자"
    assert finale["final_rewards_common"]["region_stone"]["name"] == "안동시 기억석"
