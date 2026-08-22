# ============================================================
# [v1] 분기 대화 골든 테스트 — 프롬프트 조립 + 상태 전이 (LLM 없이)
# pipeline: AI 백엔드 / 서빙 (테스트)
# 구현(요약): _llm.generate를 가짜로 갈아끼워 **프롬프트 문자열 자체**를 검증한다.
#            실측(2026-08-18)에서 확인된 회귀 4종을 잠근다 —
#              ① 내부 id 누출(clue:·fragment:)  ② history의 화자 소실
#              ③ 갈림길을 대화가 모름          ④ 종료 턴 JSON 누출
#            네트워크·LLM 0회라 기존 오프라인 스위트 속도를 해치지 않는다.
# 구현일: 2026-08-19 | 작성: kys (dialogue-rework/kys/v1)
# ============================================================
import asyncio
from unittest.mock import AsyncMock, patch

from app.services import branching_service as bs

_MOD = "app.services.branching_service"

_BRANCH = {
    "prompt": "갈림길이로다. 어느 길로 가려느냐?",
    "options": [
        {"choice_id": "main", "label": "본래 길 — 「세종대왕 동상」 쪽으로 간다",
         "next_node_id": "tour_1364932"},
        {"choice_id": "b1", "label": "혼불을 따라 「충무공 이순신 동상」로 샌다",
         "next_node_id": "tour_1364975"},
    ],
}


def _run(reply: str = '{"line":"허허 대사니라","choices":["더 묻는다","둘러본다"]}',
         grounding: str = "세종로공원은 … 녹지공간이다.", **kwargs):
    """run_branching을 LLM 없이 한 번 돌리고 (결과, 프롬프트)를 돌려준다."""
    captured: list[str] = []

    async def fake(prompt, **_):
        captured.append(prompt)
        return reply

    args = {
        "node_id": "tour_1604697", "node_name": "세종로공원", "region_id": "종로",
        "history": [], "inventory": {}, "turn": 0,
    }
    args.update(kwargs)
    with (
        patch(f"{_MOD}._grounding", new=AsyncMock(return_value=grounding)),
        patch(f"{_MOD}._llm.generate", new=fake),
    ):
        out = asyncio.run(bs.run_branching(**args))
    return out, captured[-1]


# ── ① 내부 식별자 누출 ────────────────────────────────────────
def test_inventory_ids_never_reach_the_prompt():
    """실측 회귀: 프롬프트에 clue:/fragment: 접두사가 그대로 들어가 대사로 샜다."""
    _, prompt = _run(inventory={"items": ["clue:四結", "fragment:종로_stone_3of4"]})

    assert "clue:" not in prompt
    assert "fragment:" not in prompt
    assert "단서 「四結」" in prompt
    assert "기억석 셋째 조각" in prompt


# ── ② history 화자 · 직전 선택 ────────────────────────────────
def test_history_keeps_speaker_and_echoes_last_choice():
    """실측 회귀: role이 버려져 누가 한 말인지 모른 채 프롬프트에 들어갔다."""
    history = [
        {"role": "npc", "text": "허허, 예 왔느냐"},
        {"role": "me", "text": "분수대 주변을 살펴보리라"},
    ]
    _, prompt = _run(history=history, last_choice="c0", turn=1)

    assert "도깨비: 허허, 예 왔느냐" in prompt
    assert "나그네: 분수대 주변을 살펴보리라" in prompt
    assert "[방금 고른 것] 분수대 주변을 살펴보리라" in prompt


# ── ③ 갈림길 인지 · 두 축 통합 ────────────────────────────────
def test_fork_options_are_offered_as_terminal_choices():
    """갈림길 노드의 종료 선택지 = route 갈래 id 그대로(앱이 complete로 넘기는 값)."""
    out, prompt = _run(branch=_BRANCH)

    ids = [c["id"] for c in out["choices"]]
    assert ids[-2:] == ["main", "b1"]      # 잡담 선택지 뒤에 붙는다
    assert "collect" not in ids            # 갈림길에서는 의뢰 수령이 곧 길 선택
    assert out["done"] is False
    assert "곧 길이 갈린다" in prompt        # 잡담 턴에서는 예고만


def test_choosing_a_path_ends_the_dialogue():
    """길을 고르면 종료 — 마무리 대사에 고른 길과 조각 의뢰가 함께 나간다."""
    out, prompt = _run(reply="허허, 이순신 쪽으로 가려느냐. 조각은 분수대 근처니라.",
                       branch=_BRANCH, last_choice="b1", turn=1,
                       fragment_id="종로_stone_2of4")

    assert out["done"] is True
    assert out["choices"] == []
    assert "[플레이어가 고른 다음 행선지] 혼불을 따라" in prompt
    assert "기억석 둘째 조각" in prompt
    # 조각은 '지금 이곳'에 있다 — 이 구분이 없으면 힌트가 다음 노드 장소로 샌다(실측 회귀).
    assert "지금 이곳 '세종로공원'에 숨은" in prompt
    assert "다음 행선지의 장소를 힌트로 삼지 마라" in prompt


def test_fork_node_does_not_auto_finish_on_turn_cap():
    """갈림길은 깊이상한에서 끝내지 않는다 — 길을 안 고르면 다음 노드를 정할 수 없다."""
    out, prompt = _run(reply="허허, 이제 길을 고르거라.", branch=_BRANCH, turn=9)

    assert out["done"] is False
    assert [c["id"] for c in out["choices"]] == ["main", "b1"]   # 잡담은 끝, 선택만 남음
    assert "[갈림길]" in prompt


def test_plain_node_still_finishes_on_turn_cap():
    """갈림길이 아닌 노드는 기존대로 깊이상한에서 수렴한다(회귀 방지)."""
    out, _ = _run(reply="허허, 조각을 찾아 나서거라.", turn=9)

    assert out["done"] is True
    assert out["grants"] == []          # 조각은 AR 탐색에서 — 계약 유지


def test_plain_node_offers_collect():
    out, _ = _run()
    assert [c["id"] for c in out["choices"]] == ["c0", "c1", "collect"]


# ── ④ 종료 턴 출력 방어 ──────────────────────────────────────
def test_closing_turn_strips_json_from_the_line():
    """실측 회귀: 종료 턴은 파싱을 안 해 모델이 JSON을 뱉으면 중괄호째 대사가 됐다."""
    out, _ = _run(reply='{"line":"허허, 분수대 근처를 살피거라","choices":[]}',
                  last_choice="collect")

    assert out["done"] is True
    assert out["response"] == "허허, 분수대 근처를 살피거라"
    assert "{" not in out["response"]


def test_choice_objects_are_tolerated():
    """모델이 choices를 객체로 낼 때도 텍스트를 건져낸다."""
    out, _ = _run(reply='{"line":"허허","choices":[{"text":"묻는다"},{"label":"둘러본다"}]}')

    assert [c["text"] for c in out["choices"][:2]] == ["묻는다", "둘러본다"]


# ── grounding 인자 배선 ──────────────────────────────────────
def test_region_id_is_passed_to_grounding():
    """region_id는 받고 버리던 인자였다 — 지역 워킹셋 편입에 실제로 쓰인다."""
    seen = {}

    async def fake_grounding(node_id, node_name, region_id=""):
        seen.update(node_id=node_id, region_id=region_id)
        return "원문"

    with (
        patch(f"{_MOD}._grounding", new=fake_grounding),
        patch(f"{_MOD}._llm.generate", new=AsyncMock(return_value='{"line":"허허","choices":[]}')),
    ):
        asyncio.run(bs.run_branching(node_id="tour_1", node_name="가", region_id="종로"))

    assert seen == {"node_id": "tour_1", "region_id": "종로"}


def test_wrapping_quotes_are_stripped():
    """모델이 대사를 통째로 따옴표로 감싸면 화면에 그대로 보인다(실측) — 벗긴다."""
    out, _ = _run(reply='"허허, 그늘집 기둥을 살피거라."', last_choice="collect")

    assert out["response"] == "허허, 그늘집 기둥을 살피거라."


def test_progress_is_stated_in_words():
    """진행도를 dict 그대로 넣으면 내부 키가 대사로 샌다 — 문장으로 바꿔 넣는다."""
    _, prompt = _run(player_state={"progress": 2, "required": 4})

    assert "[진행] 기억석 4조각 중 2조각을 모았다" in prompt
    assert "'progress'" not in prompt


def test_progress_absent_is_stated_as_start():
    _, prompt = _run()
    assert "[진행] 이제 막 여정을 시작한 참이다." in prompt


# ── 식음 노드 · 근거 없는 노드 ────────────────────────────────
def test_food_node_never_asks_for_a_stone():
    """실측 회귀: 식당에서 있지도 않은 기억석을 찾게 했다(식음 노드는 fragment_id가 없다)."""
    out, prompt = _run(reply="허허, 한 술 뜨고 가거라.", kind="food", last_choice="collect",
                       node_name="광화문 세종클럽")

    assert out["done"] is True
    assert "기억석" not in prompt
    assert "AR" not in prompt
    assert "요기하고 쉬어 가는 자리" in prompt


def test_food_node_terminal_choice_is_resting():
    out, prompt = _run(kind="cafe", node_name="내자상회")

    assert [c["id"] for c in out["choices"]] == ["c0", "c1", "collect"]
    assert out["choices"][-1]["text"] == "요기하고 길을 잇는다"
    assert "조각·의뢰 이야기는 꺼내지 마라" in prompt


def test_ungrounded_node_gets_a_hallucination_brake():
    """원문을 못 구한 노드(위시 합성 노드 등) — 이름만 아는 곳에서 내부 구조를 지어내지 않게."""
    with patch(f"{_MOD}._grounding", new=AsyncMock(return_value="해운대해수욕장")):
        with patch(f"{_MOD}._llm.generate", new=AsyncMock(return_value='{"line":"허허","choices":[]}')):
            import asyncio as _a
            _a.run(bs.run_branching(node_id="wish_126081", node_name="해운대해수욕장"))
    # 프롬프트 검증은 _run 경로로(같은 조건: ctx == node_name)
    _, prompt = _run(node_name="해운대해수욕장", grounding="해운대해수욕장")
    assert "지어내지 말고" in prompt


def test_grounded_node_has_no_brake():
    _, prompt = _run(node_name="세종로공원")     # 기본 grounding은 원문 텍스트
    assert "지어내지 말고" not in prompt
