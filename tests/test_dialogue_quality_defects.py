# ============================================================
# [v1] 실 LLM 시나리오 주행에서 나온 대사 품질 결함 회귀 스위트 (점검 20260909)
# pipeline: AI 백엔드 / 대사·힌트 품질
# 구현(요약): 실키(solar-pro)로 종로 코스를 끝까지 돌려 눈으로 확인한 결함 8건을
#            코드 수준에서 고정한다. 결함보고 20260904 스위트와 같은 규약 —
#            "실제 길이의 정상 출력"을 픽스처로 쓰고, 고쳐진 동작만 단언한다.
# 구현일: 2026-09-09 | 작성: pjh (agent-qa/pjh/v1)
# ============================================================
import asyncio

from app.core.wording import clean_line, humanize_ref, inventory_line
from app.pipeline.nodes.persona_inject import _apply_npc_identity
from app.pipeline.nodes.prompt_assemble import prompt_assemble
from app.scenario.generator import _dialogue_player_state
from app.scenario.node_schema import (
    _compile_strategy,
    answer_leaked,
    build_hint_ladder,
    run_qa,
)


def _prompt(**state) -> str:
    return asyncio.run(prompt_assemble(state))["prompt"]


# ── 결함 1: NPC 이름이 대사와 앱에서 갈렸다 ──────────────────────
def test_주입된_npc가_대사_페르소나의_이름을_덮는다():
    """앱이 '기와 도깨비'를 그리는데 대사는 '혈죽 도깨비'라 자칭하던 문제."""
    llm_persona = {"name": "혈죽 도깨비", "archetype": "persona",
                   "motif": "혈죽", "persona": "비장하다."}
    npc = {"name": "기와 도깨비", "archetype": "persona", "motif": "기와·처마"}

    merged = _apply_npc_identity(llm_persona, npc)

    assert merged["name"] == "기와 도깨비"
    assert merged["motif"] == "기와·처마"
    assert merged["persona"] == "비장하다."          # 말투는 LLM 합성본을 유지한다


def test_npc가_없으면_기존_동작_그대로():
    """/v1/dialogue 단독 호출 등 npc를 안 주는 경로는 하위호환."""
    persona = {"name": "혈죽 도깨비", "persona": "비장하다."}
    assert _apply_npc_identity(persona, None) == persona
    assert _apply_npc_identity(persona, {}) == persona


# ── 결함 2: 힌트가 조사에 걸려 문장째 깨졌다 ─────────────────────
def test_한글자_정답이_조사에_걸려_힌트를_깨지_않는다():
    """정답 '가'가 '가장'·'소리가'에 걸려 "정답과 연결되는 대상장"이 되던 문제."""
    quest = {
        "name": "인사동",
        "quiz": {"options": ["가", "나", "다", "라"], "answer": 0,
                 "wrong_hint": "붓끝이 지나간 자리를 다시 보거라."},
        "mission": {"type": "QUIZ_FIND", "find": "붓 파편",
                    "hints": ["골목 어귀에서 가장 오래된 간판을 살펴보거라.",
                              "붓과 먹이 만나 이을 소리가 무엇인지 떠올려 보거라."]},
    }
    ladder = build_hint_ladder(quest)

    assert ladder["H1"] == "골목 어귀에서 가장 오래된 간판을 살펴보거라."
    assert ladder["H2"] == "붓과 먹이 만나 이을 소리가 무엇인지 떠올려 보거라."
    assert "정답과 연결되는 대상" not in " ".join(ladder[k] for k in ("H1", "H2", "H3"))


def test_진짜_유출은_그대로_잡는다():
    """오탐을 줄이느라 참양성까지 놓치면 안 된다."""
    assert answer_leaked("정답은 가 이니라.", "가") is True        # 어절이 통째로 정답
    assert answer_leaked("훈민정음이 반포된 해니라", "훈민정음") is True
    assert answer_leaked("훈민을 떠올려 보거라", "훈민") is True    # 조사만 붙은 어간
    assert answer_leaked("가장 오래된 간판", "가") is False
    assert answer_leaked("이을 소리가 무엇인지", "가") is False


def test_유출은_가리되_다시_쓸_사유로_남긴다():
    """[계약 변경 20260909-2] 예전엔 '가렸으니 통과'라 재생성이 한 번도 안 돌았다.

    가리기는 응급 처치다 — 판정은 모델이 쓴 원본 힌트를 보고, QA 루프가 힌트를
    다시 만들게 한다. 실 LLM 주행에서 이 구멍 때문에 마스킹 문구가 화면까지 나갔다.
    """
    quest = {
        "name": "인사동",
        "quiz": {"options": ["훈민정음", "동국정운"], "answer": 0, "wrong_hint": "다시 보거라."},
        "mission": {"type": "QUIZ_FIND", "hints": ["훈민정음을 떠올려 보거라."]},
    }
    quest["hint_ladder"] = build_hint_ladder(quest)

    # 플레이어에게는 가려지고,
    assert "훈민정음" not in quest["hint_ladder"]["H1"]
    # QA는 원본 힌트를 보고 재생성 사유로 남긴다.
    assert run_qa(quest, {"name": "인사동", "overview": ""})["answer_leak"] is True


# ── 결함 3: 연기 지문이 앱 화면에 그대로 나갔다 ──────────────────
def test_연기_지문은_걷어내고_괄호_대사는_남긴다():
    assert clean_line("(굽고 있는 장어를 가리키며) 담백하니라") == "담백하니라"
    assert clean_line("한 점 들거라.\n(좌석을 가리킨 뒤 접시를 내민다)") == "한 점 들거라."
    # 괄호 안이 도깨비 어미로 끝나면 지문이 아니라 대사다 — 지우면 뜻이 상한다.
    body = "벽면이니라\n(문이 닫혀 있거든 옆으로 돌아가거라)"
    assert clean_line(body) == body


def test_문장_중간_지문도_걷어내되_한자_병기는_남긴다():
    """지문은 줄 머리에만 오지 않는다 — 문장 사이에도 낀다."""
    assert clean_line("궁금하지 않겠느냐? (단검을 어루만지며) 느껴지느냐?") == \
        "궁금하지 않겠느냐? 느껴지느냐?"
    # 앞에 붙여 쓴 괄호는 뜻풀이다 — 지우면 뜻이 상한다.
    gloss = "이곳은 보신각(普信閣)이 선 자리니라."
    assert clean_line(gloss) == gloss


def test_식음_프롬프트는_진행도를_주장하지_않는다():
    """조각 축 밖이라 모르는 값인데 '이제 막 여정을 시작한 참'으로 새어 나갔다."""
    prompt = _prompt(node_name="장수촌 풍천장어", stage="식음",
                     persona={"name": "숯불 도깨비"}, context="장어 전문점.", player_state={})
    assert "이제 막 여정을 시작한 참이다" not in prompt


def test_지문만_있으면_비우지_않는다():
    """오판 가능성 — 빈 대사가 더 나쁘다(clean_line v2 계약 유지)."""
    assert clean_line("(웃으며)") == "(웃으며)"


def test_본문_괄호를_메타로_오인해_지우지_않는다():
    """'규칙·유지'가 들어 있다고 본문을 통째로 자르던 문제."""
    line = "허허, 저 현판은 흥선대원군의 글씨니라. (지금도 그 규칙대로 단청을 유지하고 있느니라)"
    assert clean_line(line) == line
    # 캐릭터를 벗은 작업 설명은 여전히 걷어낸다.
    assert clean_line("여기가 보신각터니라. (간결하게 인사말을 구성해보았습니다)") == "여기가 보신각터니라."


# ── 결함 4: 식음 노드 ───────────────────────────────────────────
def test_식음_단계_프롬프트가_조각을_말리고_술을_막는다():
    prompt = _prompt(node_name="장수촌 풍천장어", stage="식음",
                     persona={"name": "숯불 도깨비"}, context="장어 전문점.")
    assert "'식음' 단계다" in prompt              # 목록에 없는 단계로 모순되게 찍히지 않는다
    assert "기억석·조각·의뢰 이야기는 꺼내지 않는다" in prompt
    assert "술·주류가 적혀 있더라도" in prompt


def test_식음_노드는_조각_탐색_힌트를_받지_않는다():
    ladder = build_hint_ladder({"name": "장수촌 풍천장어", "kind": "food"})
    joined = " ".join(ladder[k] for k in ("H1", "H2", "H3"))
    assert "조각" not in joined and "흔적" not in joined
    assert ladder["open_rule"]                    # 앱 계약(HintLadder)은 그대로 지킨다


# ── 결함 5: 피날레가 '이제 막 시작'으로 나갔다 ──────────────────
def test_피날레_프롬프트는_모아온_조각을_안다():
    meta = {"is_food": False, "is_finale": True, "stone_no": 4, "stone_total": 4}
    prompt = _prompt(node_name="신석구 사택 터", stage="완료",
                     persona={"name": "수호 도깨비"}, context="3·1운동 민족대표의 터.",
                     player_state=_dialogue_player_state(meta))
    assert "이제 막 여정을 시작한 참이다" not in prompt
    assert "3조각을 모았다" in prompt
    assert "처음 만난 것처럼 굴지 않는다" in prompt


def test_첫_노드와_식음은_진행도를_비워_둔다():
    assert _dialogue_player_state({"is_food": False, "is_finale": False,
                                   "stone_no": 1, "stone_total": 4}) == {}
    assert _dialogue_player_state({"is_food": True, "is_finale": False,
                                   "stone_no": None, "stone_total": 4}) == {}


# ── 결함 6: 힌트 사다리가 구체적→범용으로 역행했다 ──────────────
def test_힌트가_모자라도_폴백이_노드에서_유도된다():
    ladder = build_hint_ladder({
        "name": "탑골공원 팔각정",
        "mission": {"type": "PATH_TRACE", "find": "1919년 선언문 조각",
                    "hints": ["기단부터 지붕까지 팔각 구조를 따라가 보거라."]},
    })
    assert "1919년 선언문 조각" in ladder["H2"]
    assert "1919년 선언문 조각" in ladder["H3"]
    assert "지령에 나온 대상" not in ladder["H2"]      # 장소와 무관하던 옛 범용 문구


# ── 결함 7: follow.object에 문장이 통째로 박혔다 ─────────────────
def test_발자국_식별자는_짧은_이름을_쓴다():
    mission = {
        "type": "PATH_TRACE",
        "trail_object": "먹물 발자국",
        "trail_clue": "검은 먹물이 번진 발자국이 팔각정 동쪽 계단에서 시작해 기단을 따라 이어졌다",
        "steps": ["동쪽 계단", "기단", "박석 바닥"],
        "find": "선언문 조각",
    }
    atoms = _compile_strategy("S4_PHOTO_TRAIL", {"name": "탑골공원 팔각정", "mission": mission})
    follow = next(a for a in atoms if a["a"] == "follow")
    assert follow["object"] == "먹물 발자국"


# ── 결함 8: grounding이 비어도 제동이 없었다 ────────────────────
def test_원문_없는_노드에는_제동이_붙는다():
    bare = _prompt(node_name="이름만 아는 터", stage="등장", persona={}, context="")
    grounded = _prompt(node_name="보신각터", stage="등장", persona={}, context="도성의 종루.")
    assert "이름에서 알 수 있는 것과 분위기만" in bare
    assert "이름에서 알 수 있는 것과 분위기만" not in grounded


def test_빈_페르소나_슬롯과_빈_발화_라벨을_찍지_않는다():
    prompt = _prompt(node_name="보신각터", stage="등장",
                     persona={"name": "먹 도깨비", "motif": "", "archetype": "persona"},
                     context="도성의 종루.", query="")
    assert "- 모티프: \n" not in prompt and "모티프:  " not in prompt
    assert "사용자 발화" not in prompt


# ── 서수 표기 — 모델이 '첫째'를 사람으로 읽었다 ──────────────────
def test_조각_서수는_사람으로_읽히지_않는다():
    assert humanize_ref("fragment:종로_stone_1of4") == "기억석 첫 번째 조각"
    assert "첫째" not in inventory_line({"items": ["fragment:종로_stone_1of4"]})
