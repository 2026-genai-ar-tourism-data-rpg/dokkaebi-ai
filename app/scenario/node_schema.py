# ============================================================
# [v2] AI 노드 스키마 생성층 — app-v3-back/kys/v1 계약 정합
# pipeline: AI 백엔드 / 시나리오
#
# 기존 mission/quiz/objective를 유지한 채 앱 QuestNode가 직접 파싱하는 필드만 추가한다.
# - motivation: List[str]
# - strategy: List[str]
# - actions: ActionAtom JSON 목록
# - grants/requires/requires_mode
# - hint_ladder: H1/H2/H3 문자열 + open_rule 목록
# - clue: 문자열
# - success: 판정식 문자열 목록
#
# 중요:
# - kind=food/cafe는 fragment/grants를 만들지 않는다.
# - 앱 StateRef는 모르는 접두사를 조각으로 간주하므로 visit:/bonus: 같은 상태를 출력하지 않는다.
# - S7 D6는 별도 paths 필드가 아니라 listen 선택지 + 선택별 action 메타로 표현한다.
# ============================================================
from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Iterable
from typing import Any


STRATEGY_TO_MOTIVATIONS: dict[str, frozenset[str]] = {
    "S1_TALK_GATHER": frozenset({"M1", "M9"}),
    "S2_HUNT_GATHER": frozenset({"M2", "M5"}),
    "S3_RIDDLE_UNLOCK": frozenset({"M7"}),
    "S4_PHOTO_TRAIL": frozenset({"M1", "M3"}),
    "S5_PHOTO_PROOF": frozenset({"M3", "M9"}),
    "S6_ACCUMULATE": frozenset({"M1", "M8"}),
    "S7_PATRONIZE": frozenset({"M6"}),
}

ALLOWED_STRATEGIES: dict[str, frozenset[str]] = {
    motivation: frozenset(
        strategy
        for strategy, motivations in STRATEGY_TO_MOTIVATIONS.items()
        if motivation in motivations
    )
    for motivation in [f"M{i}" for i in range(1, 10)]
}

DEFAULT_STRATEGY_BY_MOTIVATION: dict[str, str] = {
    "M1": "S4_PHOTO_TRAIL",
    "M2": "S2_HUNT_GATHER",
    "M3": "S5_PHOTO_PROOF",
    # M4는 명세 제약표에 직접 연결된 전략이 없다.
    # infer_motivations()가 자연 노드에 M1, 축제 노드에 M6을 함께 부여해 플레이 가능성을 보장한다.
    "M5": "S2_HUNT_GATHER",
    "M6": "S7_PATRONIZE",
    "M7": "S3_RIDDLE_UNLOCK",
    "M8": "S6_ACCUMULATE",
    "M9": "S1_TALK_GATHER",
}

MISSION_TO_STRATEGIES: dict[str, tuple[str, ...]] = {
    "HUNT": ("S2_HUNT_GATHER",),
    "RESTORE_AR": ("S6_ACCUMULATE",),
    "PHOTO_FIND": ("S4_PHOTO_TRAIL",),
    "PATH_TRACE": ("S4_PHOTO_TRAIL",),
    "COLLECT": ("S6_ACCUMULATE",),
    "DIALOGUE_FIND": ("S1_TALK_GATHER", "S3_RIDDLE_UNLOCK"),
    "FIND": ("S6_ACCUMULATE",),
    "QUIZ_FIND": ("S3_RIDDLE_UNLOCK",),
    "DIALOGUE_COLLECT": ("S6_ACCUMULATE",),
}

CLUE_NAMES_BY_STRATEGY: dict[str, tuple[str, ...]] = {
    "S1_TALK_GATHER": ("전언", "첫 글자", "잃은 이름"),
    "S2_HUNT_GATHER": ("五影", "붉은 실", "처마 매듭"),
    "S3_RIDDLE_UNLOCK": ("ㄱ", "益", "申時", "三"),
    "S4_PHOTO_TRAIL": ("처마 3보", "문틈", "해지는 쪽"),
    "S5_PHOTO_PROOF": ("현판", "처마선", "문양"),
    "S6_ACCUMULATE": ("三墨", "四結", "五片"),
    "S7_PATRONIZE": ("溫茶", "한 모금", "김"),
}

SUPPORTED_STATE_PREFIXES = frozenset(
    {"fragment", "clue", "flag", "affinity", "coupon", "relic"}
)

_THREAT_KEYWORDS = (
    "위협",
    "침입",
    "훼손",
    "파괴",
    "공격",
    "먹그림자",
    "망각귀",
    "요괴",
    "소탕",
)
_LOSS_KEYWORDS = (
    "분실",
    "잃어버",
    "잃은",
    "사라진",
    "유실",
    "도난",
    "되찾",
    "행방",
)
_MARKET_KEYWORDS = ("시장", "상점", "상가", "장터", "쇼핑", "골목상권", "먹거리")
_NATURE_KEYWORDS = ("산", "숲", "계곡", "공원", "정원", "강", "하천", "생태", "자연")
_HERITAGE_KEYWORDS = ("궁", "궁궐", "사찰", "절", "유적", "문화재", "고택", "한옥", "성곽", "비석")
_PERSON_KEYWORDS = ("왕", "대왕", "장군", "선생", "인물", "업적", "생가", "기념관")
_MESSAGE_KEYWORDS = ("전언", "부탁", "미련", "기원", "추모", "편지", "전하다")
_TONE_MARKERS = ("니라", "허허", "거라", "구나", "로다", "느니")


class NodeContractError(ValueError):
    """app-v3-back의 QuestNode 계약을 위반한 경우."""


def infer_motivations(
    source: dict[str, Any],
    *,
    is_food: bool = False,
    is_finale: bool = False,
) -> list[str]:
    """TourAPI 메타와 overview에서 동기 1~2개를 결정한다.

    명세 충돌 처리:
    - 자연→M4만 부여하면 제약표상 가능한 전략이 없으므로 M1을 보조 동기로 붙인다.
    - 피날레는 수작업 정답지의 M3을 유지하고, S6은 구조적 예외로 허용한다.
    """
    if is_food or _content_type_id(source) == 39:
        return ["M6"]

    text = _source_text(source)
    if any(keyword in text for keyword in _LOSS_KEYWORDS):
        return ["M8"]
    if any(keyword in text for keyword in _THREAT_KEYWORDS):
        return ["M2"]

    motivations: list[str] = []
    content_type_id = _content_type_id(source)

    if is_finale:
        motivations.append("M3")

    if content_type_id == 38 or any(keyword in text for keyword in _MARKET_KEYWORDS):
        motivations.append("M6")
    elif content_type_id == 32 or any(keyword in text for keyword in _NATURE_KEYWORDS):
        motivations.extend(["M4", "M1"])
    elif content_type_id == 15:
        motivations.extend(["M4", "M6"])
    elif content_type_id == 14:
        motivations.extend(["M1", "M7"])
    elif content_type_id in {25, 28}:
        motivations.append("M7")
    else:
        if any(keyword in text for keyword in _PERSON_KEYWORDS):
            motivations.append("M3")
        if any(keyword in text for keyword in _MESSAGE_KEYWORDS):
            motivations.append("M9")
        if content_type_id == 12 or any(keyword in text for keyword in _HERITAGE_KEYWORDS):
            motivations.append("M1")

    if not motivations:
        motivations.append("M1")

    return _unique(motivations)[:2]


def strategy_is_valid(
    strategy: str,
    motivations: Iterable[str],
    *,
    is_finale: bool = False,
) -> bool:
    """명세의 동기↔전략 제약표를 검사한다.

    피날레의 M3+S6은 6절 수작업 정답지에 명시된 구조적 예외다.
    """
    if is_finale and strategy == "S6_ACCUMULATE":
        return True
    allowed_motivations = STRATEGY_TO_MOTIVATIONS.get(strategy, frozenset())
    return any(motivation in allowed_motivations for motivation in motivations)


def reroll_strategy(
    candidate: str,
    motivations: list[str],
    *,
    is_finale: bool = False,
) -> str:
    """부적합 후보를 재현 가능한 방식으로 리롤한다."""
    if strategy_is_valid(candidate, motivations, is_finale=is_finale):
        return candidate

    for motivation in motivations:
        fallback = DEFAULT_STRATEGY_BY_MOTIVATION.get(motivation)
        if fallback and strategy_is_valid(fallback, motivations, is_finale=is_finale):
            return fallback

    allowed = sorted(
        strategy
        for motivation in motivations
        for strategy in ALLOWED_STRATEGIES.get(motivation, frozenset())
    )
    if allowed:
        return allowed[0]

    # M4 단독 입력 등 명세의 빈 교집합이 외부에서 주입된 경우에도 생성은 중단하지 않는다.
    return "S1_TALK_GATHER"


def select_strategies(
    motivations: list[str],
    mission_type: str | None,
    *,
    is_food: bool = False,
    is_finale: bool = False,
) -> list[str]:
    """기존 mission을 전략 후보로 승격한 뒤 제약표로 검증한다."""
    if is_food:
        return ["S7_PATRONIZE"]
    if is_finale:
        return ["S6_ACCUMULATE"]

    selected: list[str] = []
    for candidate in MISSION_TO_STRATEGIES.get(mission_type or "", ()):  # 기존 mission 우선
        rolled = reroll_strategy(candidate, motivations)
        if rolled not in selected:
            selected.append(rolled)
        if len(selected) == 2:
            return selected

    for motivation in motivations:
        fallback = DEFAULT_STRATEGY_BY_MOTIVATION.get(motivation)
        if fallback and strategy_is_valid(fallback, motivations) and fallback not in selected:
            selected.append(fallback)
        if len(selected) == 2:
            break

    return selected or [reroll_strategy("S1_TALK_GATHER", motivations)]


def enrich_quest(quest: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """기존 퀘스트에 app-v3-back QuestNode 확장 필드를 붙인다."""
    out = copy.deepcopy(quest)
    is_food = _is_food(out)
    is_finale = bool(out.get("is_finale"))
    mission = out.get("mission") if isinstance(out.get("mission"), dict) else {}

    motivations = infer_motivations(source, is_food=is_food, is_finale=is_finale)
    strategies = select_strategies(
        motivations,
        str(mission.get("type") or ""),
        is_food=is_food,
        is_finale=is_finale,
    )

    out["motivation"] = motivations
    out["strategy"] = strategies
    out["actions"] = compile_actions(out, strategies)
    out["hint_ladder"] = build_hint_ladder(out)
    out["requires"] = _string_list(out.get("requires"))
    out["requires_mode"] = str(out.get("requires_mode") or "none")
    out["grants"] = build_base_grants(out)
    out["clue"] = _clean_optional_string(out.get("clue"))
    out["success"] = build_success(out["actions"], is_food=is_food)

    # 식음 오인 방지: 앱의 effectiveGrants와 StateRef 파서 모두에서 조각이 되지 않게 강제한다.
    if is_food:
        out["fragment_id"] = None
        out["stone_no"] = None
        out["grants"] = []
        out["clue"] = None
        out["requires"] = []
        out["requires_mode"] = "none"

    validate_app_contract(out)
    return out


def compile_actions(quest: dict[str, Any], strategies: list[str]) -> list[dict[str, Any]]:
    """전략을 app-v3-back의 ActionAtom JSON 배열로 컴파일한다."""
    name = str(quest.get("name") or "이곳")
    is_food = _is_food(quest)
    actions: list[dict[str, Any]] = [
        {"a": "goto", "place": name},
        {
            "a": "listen",
            "slot": "intro+choices",
            "choices": build_choices(quest, is_food=is_food),
        },
    ]

    if is_food:
        # D6: paths라는 별도 DTO를 만들지 않고 앱이 이미 파싱하는 choices와 raw action 메타를 사용한다.
        actions.extend(
            [
                {
                    "a": "purchase",
                    "menu": str(quest.get("name") or "현장 메뉴"),
                    "choice_id": "A",
                    "path_id": "purchase",
                    "optional": True,
                    "verification": "receipt",
                },
                {
                    "a": "answer",
                    "choice_id": "B",
                    "path_id": "free_alternative",
                    "quiz": _free_path_quiz(name),
                },
                {
                    "a": "capture",
                    "choice_id": "B",
                    "path_id": "free_alternative",
                    "targets": ["매장 외관", "메뉴판 또는 간판"],
                },
                {"a": "report", "npc": _npc_name(quest)},
            ]
        )
        return actions

    atoms: list[dict[str, Any]] = []
    for strategy in strategies:
        atoms.extend(_compile_strategy(strategy, quest))

    # S3+S4 같은 복합 전략은 정답→촬영→추적→파편 순서를 보장한다.
    actions.extend(_dedupe_and_order_atoms(atoms))
    actions.append({"a": "report", "npc": _npc_name(quest)})
    return actions


def build_choices(quest: dict[str, Any], *, is_food: bool) -> list[dict[str, Any]]:
    """ActionChoice가 파싱하는 키(id/text/flags/affinity/reward_mod)만 사용한다."""
    if is_food:
        paid: dict[str, Any] = {
            "id": "A",
            "text": "주문하고 영수증으로 인증한다.",
            "flags": ["식음주문"],
        }
        coupon_amount = _coupon_amount(quest.get("coupon"))
        if coupon_amount > 0:
            paid["reward_mod"] = {"coupon": coupon_amount}
        return [
            paid,
            {
                "id": "B",
                "text": "구매 없이 무료 대체 미션을 수행한다.",
                "flags": ["무료대체"],
            },
        ]

    return [
        {
            "id": "A",
            "text": "무슨 일이 있었는지 자세히 묻는다.",
            "flags": ["호기심"],
            "affinity": 1,
        },
        {
            "id": "B",
            "text": "해야 할 일과 보상을 먼저 확인한다.",
            "flags": ["실리"],
            "reward_mod": {"coupon": 100},
        },
        {"id": "C", "text": "주변을 먼저 살펴본다."},
    ]


def build_hint_ladder(quest: dict[str, Any]) -> dict[str, Any]:
    """앱 HintLadder.fromJson에 맞는 평면 구조를 만든다."""
    mission = quest.get("mission") if isinstance(quest.get("mission"), dict) else {}
    objective = quest.get("objective") if isinstance(quest.get("objective"), dict) else {}
    quiz = quest.get("quiz") if isinstance(quest.get("quiz"), dict) else {}

    hints = _string_list(mission.get("hints")) or _string_list(objective.get("hints"))
    h1 = hints[0] if hints else "주변에서 가장 눈에 띄는 흔적부터 살펴보거라."
    h2 = hints[1] if len(hints) > 1 else "지령에 나온 대상 가까이를 다시 확인해 보거라."
    h3 = str(quiz.get("wrong_hint") or "화면의 목표와 주변 표식을 차례로 대조해 보거라.")

    answer = _quiz_answer_text(quiz)
    h1 = _remove_answer_leak(h1, answer)
    h2 = _remove_answer_leak(h2, answer)
    h3 = _remove_answer_leak(h3, answer)

    return {
        "H1": h1,
        "H2": h2,
        "H3": h3,
        "open_rule": ["fail1|idle60", "idle90", "button"],
    }


def build_base_grants(quest: dict[str, Any]) -> list[str]:
    """앱 StateRef가 아는 6개 상태 어휘만 출력한다."""
    if _is_food(quest):
        return []

    grants = [state for state in _string_list(quest.get("grants")) if _valid_state_ref(state)]
    fragment_id = _clean_optional_string(quest.get("fragment_id"))
    if fragment_id:
        fragment_ref = f"fragment:{fragment_id}"
        if fragment_ref not in grants:
            grants.insert(0, fragment_ref)
    return _unique(grants)


def build_success(actions: list[dict[str, Any]], *, is_food: bool) -> list[str]:
    """앱이 원문 보존하는 성공 판정식 목록을 만든다."""
    if is_food:
        return ["place_verified", "one_of:purchase_verified|free_alternative_done"]

    success = ["place_verified"]
    for action in actions:
        atom = action.get("a")
        if atom == "answer":
            success.append("quiz_correct")
        elif atom == "capture":
            success.append("photo_done")
        elif atom == "follow":
            success.append(f"follow:{action.get('object', 'trail')}>={int(action.get('steps') or 1)}")
        elif atom == "defeat":
            success.append(f"defeat:{action.get('object', 'mob')}>={_count_target(action)}")
        elif atom == "tap":
            success.append(f"tap:{action.get('target', 'object')}>={_count_target(action)}")
        elif atom == "combine":
            success.append("combine_done")
    return _unique(success)


def link_state_graph(node_sequence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """단서 체인과 피날레 requires를 앱 상태 그래프 형식으로 연결한다.

    - 식음 노드는 현재 앱의 stone chapter 목록에서 제외되므로 핵심 단서 체인에 넣지 않는다.
    - path_id=b1 샛길은 본선 대체 경로이므로 피날레 전량 requires에 넣지 않는다.
    - 분기 트리의 세부 보상 동치화는 #24 route_tree 담당 범위이며, 여기서는 본선 계약을 보존한다.
    """
    sequence = copy.deepcopy(node_sequence)
    main_stones = [
        node
        for node in sequence
        if not _is_food(node) and str(node.get("path_id") or "main") == "main"
    ]
    non_finale = [node for node in main_stones if not node.get("is_finale")]
    finale = next((node for node in reversed(main_stones) if node.get("is_finale")), None)

    for current, target in zip(non_finale, main_stones[1:]):
        target_strategy = _first_strategy(target)
        clue = choose_clue_name(target_strategy, str(current.get("node_id") or ""))
        clue_ref = f"clue:{clue}"

        # 마지막 일반 노드의 단서도 단서함 카드로 지급한다.
        # 피날레는 조각 전량만 hard requires로 사용하므로 단서를 requires에 넣지는 않는다.
        current["clue"] = clue
        current["grants"] = _append_unique(_string_list(current.get("grants")), clue_ref)
        if not target.get("is_finale"):
            target["requires"] = _append_unique(_string_list(target.get("requires")), clue_ref)
            target["requires_mode"] = "soft"

    if finale is not None:
        fragment_refs = []
        for node in non_finale:
            for state in _string_list(node.get("grants")):
                if state.startswith("fragment:"):
                    fragment_refs.append(state)
        finale["requires"] = _unique(fragment_refs)
        finale["requires_mode"] = "hard" if fragment_refs else "none"

        for action in finale.get("actions") or []:
            if isinstance(action, dict) and action.get("a") == "combine":
                action["items"] = fragment_refs

    for node in sequence:
        if _is_food(node):
            node["grants"] = []
            node["requires"] = []
            node["requires_mode"] = "none"
            node["clue"] = None
            node["fragment_id"] = None
        validate_app_contract(node)

    return sequence


def choose_clue_name(target_strategy: str, seed: str) -> str:
    """다음 전략에 맞는 2~5글자 중심의 카드용 단서명을 결정론적으로 고른다."""
    candidates = CLUE_NAMES_BY_STRATEGY.get(target_strategy) or CLUE_NAMES_BY_STRATEGY["S1_TALK_GATHER"]
    digest = hashlib.sha256(f"{target_strategy}|{seed}".encode("utf-8")).digest()
    return candidates[digest[0] % len(candidates)]


def validate_app_contract(node: dict[str, Any]) -> None:
    """Flutter QuestNode/ActionAtom/HintLadder/StateRef가 안전하게 소비 가능한지 검증한다."""
    motivations = node.get("motivation")
    strategies = node.get("strategy")
    actions = node.get("actions")
    if not isinstance(motivations, list) or not all(isinstance(v, str) for v in motivations):
        raise NodeContractError("motivation은 문자열 배열이어야 합니다.")
    if not isinstance(strategies, list) or not all(isinstance(v, str) for v in strategies):
        raise NodeContractError("strategy는 문자열 배열이어야 합니다.")
    if not isinstance(actions, list) or not all(isinstance(v, dict) for v in actions):
        raise NodeContractError("actions는 객체 배열이어야 합니다.")

    for strategy in strategies:
        if not strategy.startswith("S"):
            raise NodeContractError(f"잘못된 전략 코드: {strategy}")

    for action in actions:
        if not isinstance(action.get("a"), str) or not action["a"]:
            raise NodeContractError("모든 action에는 문자열 a가 필요합니다.")
        if action["a"] == "listen":
            choices = action.get("choices")
            if not isinstance(choices, list):
                raise NodeContractError("listen.choices는 배열이어야 합니다.")
            for choice in choices:
                if not isinstance(choice, dict) or not isinstance(choice.get("id"), str):
                    raise NodeContractError("choice에는 문자열 id가 필요합니다.")
                unknown = set(choice) - {"id", "text", "flags", "affinity", "reward_mod"}
                if unknown:
                    raise NodeContractError(f"ActionChoice 미지원 키: {sorted(unknown)}")
        if action["a"] == "answer":
            quiz = action.get("quiz")
            if not isinstance(quiz, dict) or not isinstance(quiz.get("answer_idx"), int):
                raise NodeContractError("answer.quiz.answer_idx 정수가 필요합니다.")

    ladder = node.get("hint_ladder")
    if not isinstance(ladder, dict):
        raise NodeContractError("hint_ladder는 객체여야 합니다.")
    for key in ("H1", "H2", "H3"):
        if key in ladder and not isinstance(ladder[key], str):
            raise NodeContractError(f"hint_ladder.{key}는 문자열이어야 합니다.")
    if not isinstance(ladder.get("open_rule"), list):
        raise NodeContractError("hint_ladder.open_rule은 배열이어야 합니다.")

    clue = node.get("clue")
    if clue is not None and not isinstance(clue, str):
        raise NodeContractError("clue는 문자열 또는 null이어야 합니다.")

    for field in ("grants", "requires"):
        refs = node.get(field)
        if not isinstance(refs, list) or not all(isinstance(v, str) for v in refs):
            raise NodeContractError(f"{field}는 상태 문자열 배열이어야 합니다.")
        bad = [ref for ref in refs if not _valid_state_ref(ref)]
        if bad:
            raise NodeContractError(f"앱 StateRef 미지원 상태: {bad}")

    if str(node.get("requires_mode") or "none") not in {"none", "soft", "hard"}:
        raise NodeContractError("requires_mode은 none/soft/hard 중 하나여야 합니다.")

    if _is_food(node):
        if node.get("fragment_id") not in {None, ""}:
            raise NodeContractError("식음 노드는 fragment_id를 가질 수 없습니다.")
        if any(ref.startswith(("fragment:", "clue:")) for ref in node.get("grants") or []):
            raise NodeContractError("식음 노드는 조각/단서를 grants할 수 없습니다.")


def run_qa(node: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    """정답 유출·말투·grounding 범위를 자동 점검한다. 응답 DTO에는 넣지 않는다."""
    quiz = node.get("quiz") if isinstance(node.get("quiz"), dict) else {}
    answer = _quiz_answer_text(quiz)
    ladder = node.get("hint_ladder") if isinstance(node.get("hint_ladder"), dict) else {}
    hint_text = " ".join(str(ladder.get(key) or "") for key in ("H1", "H2", "H3"))
    dialogue = str(node.get("npc_dialogue") or "")
    overview = str(source.get("overview") or "")

    answer_leak = bool(answer and answer in hint_text)
    tone_ok = not dialogue or any(marker in dialogue for marker in _TONE_MARKERS)

    claims = _meaningful_tokens(dialogue)
    grounding = _meaningful_tokens(f"{source.get('name', '')} {overview}")
    unsupported = sorted(token for token in claims if len(token) >= 4 and token not in grounding)[:10]

    return {
        "answer_leak": answer_leak,
        "tone_ok": tone_ok,
        "hallucination_flag": bool(overview and unsupported),
        "unsupported_tokens": unsupported,
        "contract_ok": _contract_ok(node),
    }


def _compile_strategy(strategy: str, quest: dict[str, Any]) -> list[dict[str, Any]]:
    mission = quest.get("mission") if isinstance(quest.get("mission"), dict) else {}
    name = str(quest.get("name") or "이곳")
    fragment_target = str(mission.get("find") or "글씨파편")

    if strategy == "S1_TALK_GATHER":
        return [{"a": "tap", "target": fragment_target, "count": [0, 1]}]
    if strategy == "S2_HUNT_GATHER":
        count = max(1, _safe_int(mission.get("count"), default=3))
        return [
            {"a": "defeat", "object": str(mission.get("monster") or "먹그림자"), "count": [0, count]},
            {"a": "tap", "target": fragment_target, "count": [0, 1]},
        ]
    if strategy == "S3_RIDDLE_UNLOCK":
        return [
            {"a": "answer", "quiz": _action_quiz(quest)},
            {"a": "tap", "target": fragment_target, "count": [0, 1]},
        ]
    if strategy == "S4_PHOTO_TRAIL":
        targets = _string_list(mission.get("photo_targets")) or ["대문", "마당", "전통건물 외관"]
        steps = _string_list(mission.get("steps"))
        return [
            {"a": "capture", "targets": targets},
            {
                "a": "follow",
                "object": str(mission.get("trail_clue") or "먹물 발자국"),
                "steps": max(1, len(steps) or 3),
            },
            {"a": "tap", "target": fragment_target, "count": [0, 1]},
        ]
    if strategy == "S5_PHOTO_PROOF":
        targets = _string_list(mission.get("photo_targets")) or [f"{name}의 현판", "건물 외관"]
        return [{"a": "capture", "targets": targets}]
    if strategy == "S6_ACCUMULATE":
        if quest.get("is_finale"):
            return [{"a": "combine", "items": _string_list(quest.get("requires"))}]
        items = _string_list(mission.get("items")) or _string_list(mission.get("parts"))
        count = max(1, len(items) or _safe_int(mission.get("count"), default=3))
        target = items[0] if items else str(mission.get("object") or "흩어진 단서")
        return [{"a": "tap", "target": target, "count": [0, count]}]
    return []


def _action_quiz(quest: dict[str, Any]) -> dict[str, Any]:
    quiz = quest.get("quiz") if isinstance(quest.get("quiz"), dict) else {}
    options = _string_list(quiz.get("options"))
    answer_idx = _safe_int(quiz.get("answer"), default=0)
    if not options:
        options = ["장소의 안내와 흔적을 살핀다", "근거 없이 추측한다", "임무를 포기한다"]
        answer_idx = 0
    answer_idx = min(max(answer_idx, 0), len(options) - 1)
    return {
        "text": str(quiz.get("q") or f"{quest.get('name') or '이곳'}의 단서를 올바르게 확인한 방법은 무엇일까?"),
        "choices": options,
        "answer_idx": answer_idx,
        "correct": {"exp": 30},
        "hints": "ladder",
        "wrong_hint": str(quiz.get("wrong_hint") or "장소 정보와 화면의 목표를 다시 대조해 보거라."),
    }


def _free_path_quiz(name: str) -> dict[str, Any]:
    return {
        "text": f"{name}에서 구매 없이 장소를 인증하려면 무엇을 해야 할까?",
        "choices": ["매장 외관과 메뉴판을 확인한다", "영수증을 임의로 만든다", "아무 확인 없이 완료한다"],
        "answer_idx": 0,
        "correct": {"exp": 10},
        "hints": "ladder",
    }


def _dedupe_and_order_atoms(atoms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    priority = {"answer": 10, "capture": 20, "follow": 30, "defeat": 30, "tap": 40, "combine": 50}
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for atom in sorted(atoms, key=lambda item: priority.get(str(item.get("a")), 99)):
        key = str(atom.get("a"))
        # 한 노드에서 같은 종류의 화면 단계를 중복 생성하지 않는다.
        if key in seen:
            continue
        seen.add(key)
        result.append(atom)
    return result


def _first_strategy(node: dict[str, Any]) -> str:
    strategies = _string_list(node.get("strategy"))
    return strategies[0] if strategies else "S1_TALK_GATHER"


def _npc_name(quest: dict[str, Any]) -> str:
    npc = quest.get("npc")
    if isinstance(npc, dict) and npc.get("name"):
        return str(npc["name"])
    return "수호 도깨비"


def _content_type_id(source: dict[str, Any]) -> int | None:
    for key in ("content_type_id", "contenttypeid", "contentTypeId"):
        value = source.get(key)
        if value is not None:
            return _safe_int(value, default=None)
    return None


def _source_text(source: dict[str, Any]) -> str:
    parts = [
        source.get("name"),
        source.get("title"),
        source.get("overview"),
        source.get("cat"),
        source.get("cat1"),
        source.get("cat2"),
        source.get("cat3"),
        source.get("addr"),
        source.get("addr1"),
    ]
    return " ".join(str(part) for part in parts if part).lower()


def _coupon_amount(value: Any) -> int:
    if isinstance(value, dict):
        for key in ("amount", "value", "discount", "discount_amount"):
            if value.get(key) is not None:
                return max(0, _safe_int(value.get(key), default=0))
    if isinstance(value, (int, float, str)):
        return max(0, _safe_int(value, default=0))
    return 0


def _quiz_answer_text(quiz: dict[str, Any]) -> str:
    options = _string_list(quiz.get("options"))
    idx = _safe_int(quiz.get("answer"), default=-1)
    return options[idx] if 0 <= idx < len(options) else ""


def _remove_answer_leak(text: str, answer: str) -> str:
    if not answer or answer not in text:
        return text
    cleaned = text.replace(answer, "정답과 연결되는 대상")
    return cleaned or "주변의 근거를 다시 확인해 보거라."


def _valid_state_ref(value: str) -> bool:
    if ":" not in value:
        return False
    return value.split(":", 1)[0] in SUPPORTED_STATE_PREFIXES


def _count_target(action: dict[str, Any]) -> int:
    count = action.get("count")
    if isinstance(count, list) and count:
        return _safe_int(count[-1], default=1)
    return _safe_int(count, default=_safe_int(action.get("steps"), default=1))


def _is_food(node: dict[str, Any]) -> bool:
    return str(node.get("kind") or "") in {"food", "cafe"}


def _clean_optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _safe_int(value: Any, *, default: int | None = 0) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _append_unique(values: list[str], value: str) -> list[str]:
    return values if value in values else [*values, value]


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", text)
        if token not in {"그리고", "하지만", "이곳", "여기", "도깨비", "기억석", "조각"}
    }


def _contract_ok(node: dict[str, Any]) -> bool:
    try:
        validate_app_contract(node)
    except NodeContractError:
        return False
    return True
