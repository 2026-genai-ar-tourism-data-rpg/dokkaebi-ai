# [v1] 생성 코스 피날레 엔딩 — 지역과 마지막 장소를 사용해 종로 고정 대본 계약을 채운다.
# pipeline: 시나리오 조립 마지막 단계 (2026-09-16)
from __future__ import annotations

from app.core.wording import clean_line


def attach_endings(sequence: list[dict], region: str) -> list[dict]:
    """피날레에 A/B 선택, 복원 대사와 공통 보상을 붙인다."""
    finale = next((node for node in reversed(sequence) if node.get("is_finale")), None)
    if finale is None:
        return sequence

    place = clean_line(str(finale.get("name") or "마지막 장소"))
    area = clean_line(str(region or "이 지역"))
    title = f"{area}의 기억 복원자"
    relic = f"{area} 기억석"
    common_rewards = {
        "title": title,
        "garden_item_final": relic,
        "garden_items_per_node": [],
        "unlock": f"{area}의 기억이 복원되었습니다.",
    }
    finale["final_restore_dialogue"] = (
        f"{place}에서 모은 조각이 하나의 {relic}으로 이어졌느니라. "
        f"이제 {area}의 기억이 다시 빛을 찾았도다."
    )
    finale["endings"] = {
        "A": {
            "id": "A",
            "choice_text": "이곳의 기억을 계속 지킬게.",
            "ending": "굿 엔딩",
            "npc_dialogue": [
                f"그 마음이 {area}의 기억을 오래 지켜 줄 것이니라.",
                f"{place}에서 이어 붙인 기억을 잊지 말거라. 이제 너는 {title}니라.",
            ],
            "rewards": dict(common_rewards),
        },
        "B": {
            "id": "B",
            "choice_text": "이제 일상으로 돌아가고 싶어.",
            "ending": "노멀 엔딩",
            "npc_dialogue": [
                f"쉬고 싶은 마음도 당연하니라. {area}의 기억은 네가 되찾아 주었느니라.",
                f"{place}에서의 여정을 마음 한편에 간직해 주면 좋겠구나.",
            ],
            "rewards": dict(common_rewards),
        },
    }
    finale["final_rewards_common"] = {
        "region_stone": {"name": relic, "desc": f"{area}의 기억을 모아 복원한 기억석"},
        "story": f"{area} 지역의 기억이 복원됨",
    }
    actions = finale.get("actions")
    if isinstance(actions, list) and not any(
        action.get("slot") == "ending_choice" for action in actions if isinstance(action, dict)
    ):
        ending_action = {
            "a": "listen",
            "slot": "ending_choice",
            "choices": [
                {"id": ending["id"], "text": ending["choice_text"]}
                for ending in finale["endings"].values()
            ],
        }
        # report가 완료 신호이므로 선택은 그 직전에 플레이한다.
        report_index = next((i for i, action in enumerate(actions) if action.get("a") == "report"), len(actions))
        actions.insert(report_index, ending_action)
    return sequence
