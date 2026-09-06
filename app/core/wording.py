# ============================================================
# [v1] 프롬프트 표기 규칙 — 내부 식별자를 사람 말로 바꾸는 단일 소스
# pipeline: 공통 인프라 (프롬프트 조립 직전 단계)
# 구현(요약): 상태 참조(fragment:·clue:·flag:)·인벤토리·대화 이력·진행도를 LLM에 넣을
#            문장으로 변환한다. 내부 id가 대사로 새는 것을 여기 한 곳에서 막는다.
#            그래프(prompt_assemble)와 분기 대화(branching_service)가 **같이** 쓴다 —
#            한쪽만 고치면 같은 누출이 다른 경로로 다시 나온다(실측: "clue:x를 들고…").
# 구현일: 2026-08-19 | 작성: kys (dialogue-rework/kys/v1)
# ------------------------------------------------------------
# [v2] 메타 블록 제거 — 결함보고 20260904 #1 조치.
# 구현(요약): 실 LLM(solar-pro)이 대사 뒤에 '무엇을 어떻게 썼는지'를 덧붙인다. 노드 4개 중
#            3개의 npc_dialogue에 [규칙 준수] 목록과 (※ …) 주석이 그대로 실려 나갔고,
#            앱은 이 값을 QuestNode.npcDialogue로 화면에 그린다(= 도깨비가 프롬프트 규칙을
#            읽어 준다). 근본 원인은 qa_graph v2에서 막았지만, solar-pro는 단순 인사에도
#            "(간결하게 … 구성해보았습니다)"를 붙이는 성향이라 여기에 안전망을 둔다.
#            제거 대상: ① [머리말]만 있는 줄과 그 아래 붙는 목록  ② (※ …) 주석 블록
#                       ③ 줄 끝의 메타 괄호("… (…구성해보았습니다)")
#            ⚠️ 본문을 통째로 지우지 않는다 — 걷어낸 뒤 남는 게 없으면 원문을 돌려준다.
# 구현일: 2026-09-06 | 작성: pjh (agent-qa/pjh/v1)
# ============================================================
import re

# fragment_id 형식은 서버가 파싱하는 계약이다(finaleGateFragments) — 여기선 읽기만 한다.
_STONE_RE = re.compile(r"^(?P<region>.+)_stone_(?P<no>\d+)of(?P<total>\d+)$")
_BRANCH_RE = re.compile(r"^(?P<region>.+)_branch_(?P<branch>[\w-]+)$")

# 1~10만 우리말 서수로. 그 이상은 "N번째"로 떨어뜨린다(코스가 그렇게 길 일은 없다).
_ORDINALS = ["첫", "둘", "셋", "넷", "다섯", "여섯", "일곱", "여덟", "아홉", "열"]

# 대화 이력의 role → 프롬프트에 찍을 화자. 앱은 'npc'/'me'를 보낸다.
_SPEAKERS = {"npc": "도깨비", "assistant": "도깨비", "me": "나그네", "user": "나그네", "player": "나그네"}
_PLAYER_ROLES = {"me", "user", "player"}


# 앱은 대사를 서식 없는 Text로 그린다 — 모델이 섞어 보내는 마크업은 화면에 글자로 보인다.
# ⚠️ 꺾쇠를 통째로 지우면 안 된다: TourAPI 원문에 「<양반전>」 같은 작품명이 실제로 들어 있고
#    모델이 그걸 인용한다. 아래 태그 이름만 골라서 지운다.
_BR_RE = re.compile(r"<\s*br\s*/?\s*>", re.I)
_TAG_RE = re.compile(r"</?\s*(?:p|div|span|b|i|u|strong|em|ul|ol|li)\s*/?\s*>", re.I)
_EMPHASIS_RE = re.compile(r"(\*\*|__)(.+?)\1", re.S)

# --- 메타 블록(모델이 덧붙이는 '작업 설명') 판별 [v2] ---
# ⚠️ 대사 본문에 쓰이는 괄호(「<양반전>」·'미래상상연구실')와 구분해야 한다. 아래는
#    '괄호/대괄호가 줄을 열고' + '메타 동사가 들어 있을' 때만 걸린다.
_META_VERBS = (
    "구성", "작성", "재구성", "반영", "적용", "유지", "삭제", "추가", "강조",
    "근거해", "근거하여", "지시", "규칙", "요청", "준수", "설명", "표현 삭제",
)
# "[규칙 준수]", "[장소 실제 정보]"처럼 대괄호 머리말만 있는 줄.
_META_HEADER_RE = re.compile(r"^\[[^\[\]]{1,30}\]\s*[:：]?$")
# 목록 기호로 시작하는 줄 — 머리말 아래에 딸려 오는 항목.
_BULLET_RE = re.compile(r"^[-*•·–—]\s+")
# 줄 끝에 붙는 메타 괄호: "…이니라. (간결하게 … 구성해보았습니다)"
_META_TAIL_RE = re.compile(r"\s*[（(][^（()）]*(?:%s)[^（()）]*[）)]\s*$" % "|".join(_META_VERBS))


def _is_meta_start(line: str) -> bool:
    """이 줄에서 메타 블록이 시작되는가."""
    if _META_HEADER_RE.match(line):
        return True
    if line.startswith("※") or line.startswith("(※") or line.startswith("（※"):
        return True
    # 괄호로 줄을 열면서 메타 동사를 담고 있으면 작업 설명이다.
    return line[:1] in "(（" and any(v in line for v in _META_VERBS)


def _strip_meta_blocks(lines: list[str]) -> list[str]:
    """모델이 덧붙인 메타 블록을 걷어낸다(본문 줄은 순서 그대로 보존)."""
    kept: list[str] = []
    depth = 0            # 여는 괄호가 아직 안 닫힌 메타 블록 안인가
    in_list = False      # 대괄호 머리말 아래 목록을 먹는 중인가
    for line in lines:
        if depth > 0:                       # 여러 줄에 걸친 (…) 메타 주석
            depth += line.count("(") + line.count("（") - line.count(")") - line.count("）")
            continue
        if in_list:
            if not line or _BULLET_RE.match(line) or _is_meta_start(line):
                in_list = bool(line)        # 빈 줄이면 블록 종료
                continue
            in_list = False                 # 목록이 아닌 본문이 다시 시작됐다
        if _is_meta_start(line):
            depth = line.count("(") + line.count("（") - line.count(")") - line.count("）")
            in_list = depth <= 0
            depth = max(depth, 0)
            continue
        kept.append(_META_TAIL_RE.sub("", line).strip())
    return [line for line in kept if line]


def clean_line(text: str) -> str:
    """LLM 대사에서 화면에 글자로 보일 마크업·인용부호를 걷어낸다.

    모델이 대사를 따옴표로 감싸 여러 문단으로 뱉는 일이 잦다(실측: 제주). 줄 **양끝의**
    큰따옴표만 떼고 빈 줄은 버린다 — 문장 가운데 따옴표('미래상상연구실' 같은 고유명)는
    그대로 둬야 하므로 통째로 지우지 않는다.

    [v2] 대사 뒤에 붙는 '작업 설명'([규칙 준수] 목록 · (※ …) 주석 · 줄 끝 메타 괄호)도
    걷어낸다 — 앱이 이 값을 그대로 화면에 그린다(결함보고 20260904 #1).
    """
    text = _BR_RE.sub("\n", text or "")
    text = _TAG_RE.sub("", text)
    text = _EMPHASIS_RE.sub(r"\2", text)          # **강조** → 강조
    lines = [ln.strip().strip('"“”').strip() for ln in text.split("\n")]
    body = [ln for ln in lines if ln]
    # [v2] 모델이 덧붙인 작업 설명을 걷어낸다. 전부 메타로 판정되면(=오판 가능성)
    #      본문을 비우는 대신 걷어내기 전 상태를 돌려준다 — 빈 대사가 더 나쁘다.
    return "\n".join(_strip_meta_blocks(body) or body)


def _ordinal(n: int) -> str:
    """1 → '첫째', 11 → '11번째'."""
    return f"{_ORDINALS[n - 1]}째" if 1 <= n <= len(_ORDINALS) else f"{n}번째"


def humanize_ref(ref: str) -> str:
    """상태 참조 한 개를 대사에 그대로 써도 되는 말로. 모르는 형식이면 접두사만 뗀다.

    fragment:종로_stone_3of4 → 기억석 셋째 조각 / clue:四結 → 단서 「四結」
    """
    ref = (ref or "").strip()
    if not ref:
        return ""
    kind, _, rest = ref.partition(":")
    if not rest:                      # 접두사 없는 값은 그대로 둔다
        kind, rest = "", ref

    if kind == "fragment":
        stone = _STONE_RE.match(rest)
        if stone:
            return f"기억석 {_ordinal(int(stone.group('no')))} 조각"
        if _BRANCH_RE.match(rest):
            return "샛길에서 얻은 기억석 조각"
        return "기억석 조각"
    if kind == "clue":
        return f"단서 「{rest}」"
    if kind == "flag":
        return f"「{rest}」의 자취"
    return rest


def inventory_line(inventory: dict | None) -> str:
    """인벤토리를 프롬프트 한 줄로. 내부 id는 절대 그대로 넣지 않는다."""
    items = (inventory or {}).get("items") or []
    named = [w for w in (humanize_ref(str(i)) for i in items) if w]
    return "지금까지 모은 것: " + ", ".join(named) if named else "아직 모은 것이 없다."


def history_text(history: list[dict] | None, max_turns: int = 6) -> str:
    """대화 이력을 화자와 함께 최근 max_turns개만. 글자 수로 자르면 문장이 잘려 뜻이 깨진다."""
    rows = [h for h in (history or []) if str(h.get("text", "")).strip()]
    return "\n".join(
        f"{_SPEAKERS.get(str(h.get('role', '')), '나그네')}: {str(h['text']).strip()}"
        for h in rows[-max_turns:]
    )


def last_player_text(history: list[dict] | None) -> str:
    """플레이어가 마지막으로 한 말(=직전에 고른 선택지 문구). 없으면 빈 문자열.

    선택 id(c0/b1)는 LLM에 아무 의미가 없으므로, 프롬프트에는 이 문구를 넣는다.
    """
    for h in reversed(history or []):
        if str(h.get("role", "")) in _PLAYER_ROLES and str(h.get("text", "")).strip():
            return str(h["text"]).strip()
    return ""


def progress_line(player_state: dict | None) -> str:
    """진행도를 한 줄로. 서버가 넘기는 키 이름이 확정되지 않아 아는 것만 골라 쓴다."""
    st = player_state or {}
    if not st:
        return "이제 막 여정을 시작한 참이다."

    parts: list[str] = []
    done, total = st.get("progress"), st.get("required") or st.get("stone_total")
    if isinstance(done, int) and isinstance(total, int) and total > 0:
        parts.append(f"기억석 {total}조각 중 {done}조각을 모았다")
    elif isinstance(done, int):
        parts.append(f"기억석 {done}조각을 모았다")

    held = st.get("items") or st.get("collected_fragment_ids") or []
    if isinstance(held, list) and held:
        named = [w for w in (humanize_ref(str(i)) for i in held) if w]
        if named:
            parts.append("품에 든 것은 " + ", ".join(named) + "이다")

    return " · ".join(parts) if parts else "이제 막 여정을 시작한 참이다."
