# ============================================================
# [v1] 프롬프트/대사 표기 규칙 테스트 — core.wording
# pipeline: 공통 인프라 (테스트)
# 구현(요약): ① 상태 참조 사람말 변환이 **지역이 바뀌어도** 성립하는지
#            ② 대사 마크업 제거가 원문 인용(「<양반전>」)을 해치지 않는지
#            실측(2026-08-19, 6개 지역 순회)에서 나온 회귀를 잠근다. LLM·네트워크 0.
# 구현일: 2026-08-19 | 작성: kys (dialogue-rework/kys/v1)
# ------------------------------------------------------------
# [v2] 메타 블록 제거 회귀 — 결함보고 20260904 #1.
# 커버: ③ 실 LLM(solar-pro)이 대사 뒤에 붙인 [규칙 준수] 목록·(※ …) 주석·줄 끝 메타
#         괄호를 걷어내되, 본문 괄호와 작품명은 그대로 두는지. 실측 4건을 그대로 박는다.
# 구현일: 2026-09-06 | 작성: pjh (agent-qa/pjh/v1)
# ============================================================
from app.core.wording import (
    clean_line,
    history_text,
    humanize_ref,
    inventory_line,
    last_player_text,
    progress_line,
)


# ── 지역이 바뀌어도 조각 이름이 사람 말로 나오는가 ─────────────
def test_stone_names_survive_any_region_label():
    """fragment_id에는 자동 판정된 지역 라벨이 박힌다 — 6개 지역 실측값 그대로."""
    cases = {
        "fragment:해운대구_stone_1of4": "기억석 첫 번째 조각",
        "fragment:경주시_stone_2of4": "기억석 두 번째 조각",
        "fragment:완산구_stone_3of4": "기억석 세 번째 조각",
        "fragment:서귀포시_stone_4of4": "기억석 네 번째 조각",
        "fragment:정선군_stone_3of3": "기억석 세 번째 조각",
        "fragment:이 지역_stone_1of5": "기억석 첫 번째 조각",   # 주소 판정 실패 시 폴백 라벨
    }
    for ref, expected in cases.items():
        assert humanize_ref(ref) == expected, ref


def test_branch_fragment_and_long_courses():
    assert humanize_ref("fragment:강릉시_branch_b1") == "샛길에서 얻은 기억석 조각"
    assert humanize_ref("fragment:종로_stone_11of12") == "기억석 11번째 조각"   # 서수표 밖
    assert humanize_ref("fragment:알수없는형식") == "기억석 조각"


def test_other_state_kinds():
    assert humanize_ref("clue:四結") == "단서 「四結」"
    assert humanize_ref("flag:도깨비와 인사") == "「도깨비와 인사」의 자취"
    assert humanize_ref("접두사없음") == "접두사없음"
    assert humanize_ref("") == ""


def test_inventory_line():
    assert inventory_line(None) == "아직 모은 것이 없다."
    assert inventory_line({"items": []}) == "아직 모은 것이 없다."
    line = inventory_line({"items": ["clue:ㄱ", "fragment:완산구_stone_2of4"]})
    assert line == "지금까지 모은 것: 단서 「ㄱ」, 기억석 두 번째 조각"
    assert "clue:" not in line and "fragment:" not in line


# ── 대사 마크업 정리 ─────────────────────────────────────────
def test_markup_is_stripped_but_quoted_titles_survive():
    """실측(정선군): 모델이 <br/>을 섞어 보내 앱 Text에 글자로 보였다.

    반대로 「<양반전>」처럼 꺾쇠 안 작품명은 TourAPI 원문에 실제로 있으므로 살려야 한다.
    """
    assert clean_line("앞줄<br/>뒷줄") == "앞줄\n뒷줄"
    assert clean_line("앞줄<BR />뒷줄") == "앞줄\n뒷줄"
    assert clean_line("<p>도깨비니라</p>") == "도깨비니라"
    assert clean_line("**분수대** 근처니라") == "분수대 근처니라"
    assert clean_line("연암의 <양반전>을 아느냐") == "연암의 <양반전>을 아느냐"
    assert clean_line("  허허  ") == "허허"


def test_quote_wrapped_paragraphs_are_flattened():
    """실측(제주): 모델이 대사를 따옴표로 감싸 문단을 나눠 뱉어 화면에 그대로 보였다."""
    raw = '허허, 돌벤치를 살펴봐라~"  \n\n"광치기해변 쪽도 보거라.'
    assert clean_line(raw) == "허허, 돌벤치를 살펴봐라~\n광치기해변 쪽도 보거라."


def test_inner_quotes_are_preserved():
    """문장 가운데 인용은 고유명일 수 있다 — 지우면 뜻이 상한다."""
    got = clean_line("창의마루 3층 '미래상상연구실' 벽면이니라")
    assert got == "창의마루 3층 '미래상상연구실' 벽면이니라"


# ── 메타 블록 제거 [v2] — 실측 유출 4건 ────────────────────────
#
# 2026-09-04 실 LLM 점검에서 노드 4개 중 3개의 npc_dialogue에 프롬프트 지시문이 실려
# 나갔다. 앱은 이 값을 QuestNode.npcDialogue로 그대로 그린다.

_BODY_민영환 = (
    "허허, 이 자리가 바로 민영환 선생이 을사늑약의 치욕을 견디지 못해 "
    "순절로 목숨을 바친 곳이니라. 그 뜻을 헤아리지 않겠느냐?"
)


def test_bracket_rule_block_and_its_bullets_are_dropped():
    """실측: 대사 뒤에 '[규칙 준수]' 머리말과 작성 지침 목록이 그대로 따라 나왔다."""
    raw = (
        f"{_BODY_민영환}\n"
        "[규칙 준수]\n"
        "- 실제 소장 정보·유래·조형물(유서·단검) 등 실제 정보만 기술\n"
        '- "~니라" 어미와 감탄사 "허허" 적용\n'
        "- 3문장으로 소개 + 가벼운 질문 구성"
    )
    assert clean_line(raw) == _BODY_민영환


def test_asterisk_annotation_block_is_dropped():
    """실측: '(※ …)' 주석이 여러 줄에 걸쳐 붙었다."""
    raw = (
        "여기가 바로 도성의 시간을 지키던 보신각터니라. 그 이야기를 듣고 싶으냐?\n"
        "(※ [장소 실제 정보]의 연도·사건·현황을 활용해 재구성.\n"
        '   "백성들" 등 추정 표현 삭제)'
    )
    assert clean_line(raw) == "여기가 바로 도성의 시간을 지키던 보신각터니라. 그 이야기를 듣고 싶으냐?"


def test_multiline_parenthetical_worknote_is_dropped():
    """실측: 괄호로 시작하는 여러 줄 작업 설명."""
    raw = (
        "남산 팔각정도 이를 본받았겠다!\n"
        "(소장 정보에 근거해 역사적 사실과 건축적 특징을 강조하며,\n"
        " 감탄사와 거친 어말어미 '~느니라/~겠다'를 유지)"
    )
    assert clean_line(raw) == "남산 팔각정도 이를 본받았겠다!"


def test_trailing_meta_parenthesis_is_dropped():
    """solar-pro는 단순 인사에도 '(간결하게 … 구성해보았습니다)'를 덧붙인다."""
    raw = "안녕하신가, 나그네여. 허허. (간결하게 인사말을 구성해보았습니다)"
    assert clean_line(raw) == "안녕하신가, 나그네여. 허허."


def test_body_parentheses_are_not_meta():
    """본문 괄호·작품명은 메타가 아니다 — 지우면 뜻이 상한다."""
    raw = "창의마루 3층 '미래상상연구실' 벽면이니라\n(문이 닫혀 있거든 옆으로 돌아가거라)"
    assert clean_line(raw) == raw
    assert clean_line("연암의 <양반전>을 아느냐") == "연암의 <양반전>을 아느냐"


def test_all_meta_input_keeps_body_rather_than_emptying():
    """전부 메타로 판정되면 오판일 수 있다 — 빈 대사를 내보내지 않는다."""
    assert clean_line("[규칙 준수]\n- 3문장으로 구성") == "[규칙 준수]\n- 3문장으로 구성"


# ── 이력·진행도 ─────────────────────────────────────────────
def test_history_and_last_player_text():
    history = [
        {"role": "npc", "text": "허허"},
        {"role": "me", "text": "분수대를 살핀다"},
        {"role": "npc", "text": "그러하냐"},
    ]
    assert history_text(history) == "도깨비: 허허\n나그네: 분수대를 살핀다\n도깨비: 그러하냐"
    assert last_player_text(history) == "분수대를 살핀다"
    assert last_player_text([]) == ""


def test_history_keeps_only_recent_turns():
    history = [{"role": "npc", "text": f"{i}"} for i in range(10)]
    assert history_text(history, max_turns=3) == "도깨비: 7\n도깨비: 8\n도깨비: 9"


def test_progress_line():
    assert progress_line(None) == "이제 막 여정을 시작한 참이다."
    assert progress_line({"progress": 2, "required": 4}) == "기억석 4조각 중 2조각을 모았다"
    got = progress_line({"progress": 1, "required": 3, "items": ["clue:ㄴ"]})
    assert got == "기억석 3조각 중 1조각을 모았다 · 품에 든 것은 단서 「ㄴ」이다"
