# ============================================================
# [v1] 분기 대화 서비스 — 선택지 + 연계(인벤토리) + 종료 (기획 8-D·7-C)
# pipeline: AI 백엔드 / 서빙 (찐 RPG 대화: 동적 생성, 구조적 종료)
# 구현(요약): 노드 grounding + 인벤토리·history 주입 → LLM이 대사+선택지(2) 생성.
#            'collect' 선택 또는 깊이상한(turn>=max) → 조각 grants + done. 항상 수렴.
# 구현일: 2026-06-19 | 작성: kys (rpg-dialogue/kys/v1)
# ------------------------------------------------------------
# [v2] 갈림길을 대화 안으로 흡수 + 프롬프트 위생. 실측(2026-08-18) 결과 반영.
# 구현(요약): ① 갈림길(branch)을 인자로 받아 **경로 선택을 대화의 종료 행위로** 만든다.
#              전에는 route 선택(main|b1)과 대화 선택(c0|c1|collect)이 축이 갈라져
#              도깨비가 갈림길을 모른 채 무관한 선택지를 지어냈다.
#            ② history의 role을 살리고 '방금 고른 것'을 프롬프트에 명시 — 선택이
#              다음 대사에 반영되지 않던 문제(선택이 무의미했음).
#            ③ 인벤토리·조각을 core.wording으로 사람 말 변환 — "clue:x를 들고…"처럼
#              내부 id가 대사로 새던 누출 차단.
#            ④ 종료 턴에도 출력 파싱 방어(모델이 JSON을 뱉으면 중괄호째 대사가 됐다).
#            ⑤ region_id를 grounding 재조회에 전달(지금까지 받고 버리던 인자).
#            ⑥ 식음 노드(kind=food/cafe)는 '요기 권유'로 마무리 — 조각 의뢰 금지.
#              실측: 식당에서 "지하 다이닝 홀 청동 부조 사이를 살펴라"며 있지도 않은
#              기억석을 찾게 했다(식음 노드는 fragment_id가 없어 앱이 collect를 건너뛴다).
#            ⑦ 원문(overview)을 못 구한 노드에서는 구체적 사실을 지어내지 말라고 명시.
#            상태 전이: 잡담 → (경로/의뢰 선택 or 깊이상한) → 종료. 갈림길 노드는
#            깊이상한에서 끝내지 않고 **길을 고르게** 한다 — 안 고르면 다음 노드가 없다.
# 구현일: 2026-08-19 | 작성: kys (dialogue-rework/kys/v1)
# ============================================================
import json

from app.config import get_settings
from app.core.logger import get_logger
from app.core.wording import (
    clean_line,
    history_text,
    humanize_ref,
    inventory_line,
    last_player_text,
    progress_line,
)
from app.llm.client import get_llm
from app.region.memory_cache import get_region_cache

logger = get_logger(__name__)

_llm = get_llm()
_TONE = "도깨비 말투(어미 '~니라/~겠느냐', 감탄 '허허'), 2~3문장, 군더더기·메타설명 금지."
_COLLECT_ID = "collect"
_COLLECT_TEXT = "의뢰를 받고 기억석을 찾아 나선다"
_REST_TEXT = "요기하고 길을 잇는다"
_FOOD_KINDS = {"food", "cafe"}
# 원문을 못 구했을 때(이름만 아는 장소) 붙이는 제동. 없으면 모델이 내부 구조를 지어낸다.
_NO_SOURCE_RULE = (
    "이 장소는 이름 말고 확인된 자료가 없다. 내부 구조·시설·역사를 지어내지 말고, "
    "이름에서 알 수 있는 것과 분위기만 짧게 말하라."
)


async def _grounding(node_id: str, node_name: str, region_id: str = "") -> str:
    """대사 근거 텍스트 확보: 지역캐시(미스 시 캐시가 자체적으로 TourAPI 재조회) → 이름."""
    ctx = await get_region_cache().get_text(node_id, region_id=region_id)
    return ctx or node_name or ""


def _options(branch: dict | None) -> list[dict]:
    """갈림길 갈래 목록(없으면 빈 리스트). choice_id/label만 신뢰한다."""
    opts = (branch or {}).get("options") or []
    return [o for o in opts if isinstance(o, dict) and o.get("choice_id")]


def _terminal_choices(branch: dict | None, kind: str = "spot") -> list[dict]:
    """이 노드 대화를 끝내는 선택지. 갈림길이면 '길 고르기'가 곧 종료 행위다.

    갈림길 노드에서 choice_id는 route_tree의 갈래 id(main|b1) 그대로다 —
    앱이 이 값을 서버 complete에 그대로 넘겨 다음 노드가 정해진다(계약).
    """
    opts = _options(branch)
    if opts:
        return [
            {"id": str(o["choice_id"]), "text": str(o.get("label") or o["choice_id"])}
            for o in opts
        ]
    text = _REST_TEXT if kind in _FOOD_KINDS else _COLLECT_TEXT
    return [{"id": _COLLECT_ID, "text": text}]


def _fork_block(branch: dict | None) -> str:
    """종료 턴 프롬프트에 붙는 갈림길 지시문. 고정 문구 대신 LLM이 두 길을 권하게 한다."""
    opts = _options(branch)
    if not opts:
        return ""
    lines = "\n".join(f"  - {o['choice_id']} — {o.get('label') or o['choice_id']}" for o in opts)
    return (
        "\n[갈림길] 이 자리에서 길이 갈린다. 아래 두 길을 장소 정보에 근거해 각각 한 문장으로 권하고, "
        "어느 쪽으로 갈지 고르게 하라.\n" + lines
    )


async def run_branching(
    *, node_id: str, node_name: str = "", region_id: str = "",
    history: list[dict] | None = None, inventory: dict | None = None,
    last_choice: str | None = None, turn: int = 0, fragment_id: str | None = None,
    player_state: dict | None = None, branch: dict | None = None, kind: str = "spot",
) -> dict:
    """[분기 대화] 한 턴 생성. 반환 {response, choices[], grants[], done}.

    종료 조건 = 의뢰 수령('collect') 또는 갈림길에서 길을 고름(main|b1).
    갈림길이 아닌 노드는 깊이상한(turn>=max)에서도 종료한다.
    갈림길 노드는 상한에 닿아도 종료하지 않고 **길 선택만 남긴다** — 선택이 없으면
    다음 노드를 정할 수 없어 코스가 끊기기 때문(잡담은 그 시점에 끝난다).
    담당: 상태머신·종료·갈림길 = 김예슬 / 선택지·프롬프트 품질 = 박준형.
    """
    s = get_settings()
    ctx = await _grounding(node_id, node_name, region_id)
    inv = inventory_line(inventory)
    progress = progress_line(player_state)
    terminal = _terminal_choices(branch, kind)
    is_food = kind in _FOOD_KINDS
    # 원문 없이 이름만 확보된 경우(위시 합성 노드·식음 후보 등) — 환각 제동을 건다.
    grounded = bool(ctx) and ctx != (node_name or "")
    terminal_ids = {c["id"] for c in terminal}

    chose_terminal = last_choice in terminal_ids
    depth_reached = turn >= s.max_dialogue_turns
    is_fork = bool(_options(branch))
    # 갈림길에서는 깊이상한이 종료가 아니라 '잡담 종료'다. 길을 골라야 끝난다.
    done = chose_terminal or (depth_reached and not is_fork)
    place = node_name or node_id

    if done or depth_reached:
        picked = next((c["text"] for c in terminal if c["id"] == last_choice), "")
        head = (
            f"너는 '{place}'을(를) 지키는 도깨비다.\n[장소 정보] {ctx}\n"
            f"[플레이어가 모은 것] {inv}\n[진행] {progress}\n"
            + (f"[플레이어가 고른 다음 행선지] {picked} — 아직 떠나기 전이다.\n" if picked else "")
        )
        if is_food:
            # 식음 노드는 기억석이 없다(fragment_id 없음 → 앱이 collect를 건너뛴다).
            # 여기서 조각을 찾으라고 하면 플레이어는 없는 것을 뒤진다(실측 회귀).
            body = (
                "이곳은 요기하고 쉬어 가는 자리다. 조각·의뢰 이야기는 꺼내지 말고, "
                "여정 중에 한 술 뜨고 가라고 권하라."
                + (" 아는 범위에서 무엇을 맛보면 좋을지 한마디 곁들여도 좋다."
                   if grounded else " 메뉴·시설은 확인된 바 없으니 지어내지 마라.")
            )
        else:
            # ⚠️ 고른 길은 '앞으로 갈 곳'이고 조각은 '지금 이곳'에 있다. 이 둘을 구분해 주지
            #    않으면 모델이 힌트를 다음 노드 장소로 준다(실측에서 실제로 그랬다).
            stone = humanize_ref(f"fragment:{fragment_id}") if fragment_id else "이곳의 기억석 조각"
            body = (
                f"플레이어에게 **지금 이곳 '{place}'에 숨은** {stone}을(를) 찾으라는 의뢰를 주고, "
                f"어디를 AR로 살펴봐야 할지 힌트를 준다.\n"
                f"힌트는 반드시 위 [장소 정보]에 나오는 '{place}' 안의 지형·건물·조형물이어야 한다 — "
                f"다음 행선지의 장소를 힌트로 삼지 마라."
            )
        prompt = (
            head + body
            + (_fork_block(branch) if not done else "")
            + ("" if grounded else f"\n{_NO_SOURCE_RULE}")
            + f"\n{_TONE}"
        )
        line = _line_only(await _llm.generate(prompt))
        if done:
            # grants는 비움 — 조각은 AR 탐색(앱)에서 획득. done=대화 종료→탐색으로.
            logger.info("분기 대화 종료: node=%s 선택=%s", node_id, last_choice)
            return {"response": line, "choices": [], "grants": [], "done": True}
        # 갈림길 · 깊이상한 → 잡담은 끝내고 길 선택만 남긴다(아직 done 아님).
        logger.info("갈림길 선택 대기: node=%s 갈래=%s", node_id, sorted(terminal_ids))
        return {"response": line, "choices": terminal, "grants": [], "done": False}

    prompt = (
        f"너는 '{place}'을(를) 지키는 도깨비 NPC다. 장소 역사에 근거해서만 말한다.\n"
        f"[장소 정보] {ctx}\n[플레이어가 모은 것] {inv}\n[진행] {progress}\n"
        f"[지금까지 대화]\n{history_text(history, s.dialogue_history_turns)}\n"
        + (f"[방금 고른 것] {last_player_text(history)}\n" if last_player_text(history) else "")
        + ("[귀띔] 이 자리에서 곧 길이 갈린다 — 아직 고르게 하지는 말고 흘리듯 언급해도 좋다.\n"
           if is_fork else "")
        + ("" if grounded else f"{_NO_SOURCE_RULE}\n")
        + ("[이곳은 요기하는 자리다 — 조각·의뢰 이야기는 꺼내지 마라.]\n" if is_food else "")
        + f"규칙: {_TONE} 그리고 플레이어가 고를 짧은 선택지 2개를 제안한다. "
        f"방금 고른 것이 있으면 그 말을 받아서 이어가라. 모은 단서가 있으면 언급해도 좋다.\n"
        f'반드시 아래 JSON만 출력: {{"line": "<대사>", "choices": ["<선택지1>", "<선택지2>"]}}'
    )
    raw = await _llm.generate(prompt)
    line, choices = _parse(raw)
    objs = [{"id": f"c{i}", "text": t} for i, t in enumerate(choices[:2])]
    objs.extend(terminal)          # 갈림길이면 길 고르기, 아니면 의뢰 수령
    return {"response": line, "choices": objs, "grants": [], "done": False}


def _json_obj(raw: str) -> dict | None:
    """LLM 출력에서 첫 JSON 오브젝트만 떼어낸다. 실패하면 None."""
    try:
        return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except (ValueError, TypeError):
        return None


def _unquote(text: str) -> str:
    """모델이 대사 전체를 따옴표로 감싸는 일이 잦다 — 화면에 그대로 보이므로 벗긴다."""
    text = (text or "").strip()
    for q in ('"', "'", "“", "”"):
        if len(text) > 1 and text[0] == q and text[-1] in ('"', "'", "“", "”"):
            return text[1:-1].strip()
    return text


def _line_only(raw: str) -> str:
    """대사 한 덩어리만 뽑는다. 모델이 JSON을 뱉어도 중괄호가 대사로 나가지 않게.

    종료 턴은 평문을 요구하지만 모델이 앞 턴 형식을 따라 JSON을 내는 일이 있다(방어).
    """
    raw = (raw or "").strip()
    data = _json_obj(raw)
    if isinstance(data, dict):
        line = str(data.get("line") or "").strip()
        if line:
            return clean_line(_unquote(line))
    return clean_line(_unquote(raw))


def _parse(raw: str) -> tuple[str, list[str]]:
    """LLM 출력에서 {line, choices} 추출. 실패 시 원문+기본 선택지로 폴백.

    choices 원소는 문자열이거나 {text|label}일 수 있다(모델이 형식을 흔든다).
    """
    fallback = ["도깨비에게 더 물어본다", "주변을 둘러본다"]   # 파싱 실패 시 진행은 막지 않는다
    data = _json_obj(raw)
    if not isinstance(data, dict):
        return (raw or "").strip(), fallback

    line = clean_line(_unquote(str(data.get("line") or ""))) or clean_line(raw or "")
    choices: list[str] = []
    for c in data.get("choices") or []:
        text = c if isinstance(c, str) else (c.get("text") or c.get("label") if isinstance(c, dict) else "")
        if isinstance(text, str) and clean_line(text):
            choices.append(clean_line(text))
    return line, (choices or fallback)
