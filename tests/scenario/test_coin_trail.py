# ============================================================
# [v1] 발자국 추적 → 도깨비가 흘리고 간 엽전 줍기 — AI 문구 회귀 테스트.
# pipeline: AI 백엔드 / 시나리오 (미션 문구)
# 구현(요약): 앱 AR이 발자국 대신 엽전을 그리므로, 코스 생성 프롬프트·LLM 실패 기본값·
#            S4 follow 원자·종로 시연 코스가 '발자국'이 아니라 엽전을 말하는지 고정한다.
# 구현일: 2026-09-18 | 작성: ljs (coin-trail/ljs/v1)
# ============================================================
import json

from app.scenario.jongno_script import generate_jongno_script
from app.scenario.node_content import _PROMPTS, generic_mission
from app.scenario.node_schema import TRAIL_CLUE_DEFAULT, TRAIL_OBJECT_DEFAULT, _compile_strategy

_TRAIL_TYPES = ("PHOTO_FIND", "PATH_TRACE")


def test_자취를_만드는_프롬프트는_엽전을_말한다():
    for mtype in _TRAIL_TYPES:
        prompt = _PROMPTS[mtype]
        assert "엽전" in prompt, mtype
        assert "발자국" not in prompt, mtype


def test_LLM이_자취를_안_주면_엽전_기본값을_쓴다():
    for mtype in _TRAIL_TYPES:
        m = generic_mission("탑골공원", mtype)
        assert m["trail_object"] == TRAIL_OBJECT_DEFAULT == "도깨비 엽전", mtype
        assert m["trail_clue"] == TRAIL_CLUE_DEFAULT, mtype
        assert "발자국" not in m["trail_clue"], mtype


def test_follow_원자는_자취_이름이_없으면_엽전이다():
    mission = {"type": "PATH_TRACE", "steps": ["동쪽 계단", "기단", "박석 바닥"]}
    atoms = _compile_strategy("S4_PHOTO_TRAIL", {"name": "탑골공원 팔각정", "mission": mission})
    follow = next(a for a in atoms if a["a"] == "follow")
    assert follow["object"] == "도깨비 엽전"
    assert follow["steps"] == 3


def test_종로_시연_코스에_먹물_발자국이_남지_않는다():
    text = json.dumps(generate_jongno_script(region="종로"), ensure_ascii=False)
    assert "먹물 발자국" not in text
    assert "follow:도깨비 엽전>=3" in text
    # 단서 키는 다음 노드 requires와 이어져 있어 그대로다.
    assert "처마 3보" in text
