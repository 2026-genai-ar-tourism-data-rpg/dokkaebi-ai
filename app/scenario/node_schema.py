# ============================================================
# [v2] AI 노드 스키마 생성층 — app-v3-back/kys/v1 계약 정합
# 구현일: 2026-07-30 | 작성: pjh (node-schema-gen/pjh/v1)
# ------------------------------------------------------------
# [v3] 리뷰(#30) 반영 — 생성 순서·매핑·단서 유일성·NPC 합성·QA 수정
# pipeline: AI 백엔드 / 시나리오
#
# 기존 mission/quiz/objective를 유지한 채 앱 QuestNode가 직접 파싱하는 필드만 추가한다.
# - motivation: List[str] / strategy: List[str] / actions: ActionAtom JSON
# - grants/requires/requires_mode / hint_ladder / clue / success
#
# v3 변경 (리뷰 결함 수정):
# ① 순서 역전 해소 — select_mission_type()으로 "동기 → 허용 전략 → 미션 타입"을
#    콘텐츠 생성 **이전**에 결정한다(미션 텍스트와 액션의 모순 차단).
# ② S7은 식음 전용 — spot 노드에서 제외 + 상권 spot은 M6에 M1을 짝지어 플레이 보장.
#    (안전망: _compile_strategy에 S7 분기 추가, 빈 액션 노드 가드)
# ③ 위협·분실 키워드 = 보조 오버라이드 — 복원·중건 등 역사 서술 문맥이면 미발동,
#    발동해도 기본 동기를 버리지 않고 앞에 얹는다. ctid 32(숙박) 오매핑 제거,
#    cat 코드(A01/A03/A04/A05) 프리픽스 매핑 추가.
#    ※ 키워드 휴리스틱은 폴백이다 — 1차 분류는 node_content.classify_motivations(LLM).
# ④ 단서 이름 = 단서설계규칙.md 준수 — 다음 노드의 실제 수행 조건(개수·대상·정답)에서
#    유도(derive_clue_name) + 시나리오 내 유일성 보장.
# ⑤ 8-B NPC 합성(synthesize_npc) — 이름·모티프·말투·동기 필드를 결정적으로 생성.
# ⑥ run_qa 환각 체크에 조사(助詞) 스트리핑 — 한국어 오탐 완화. 배선은 generator.
#
# 중요(유지):
# - kind=food/cafe는 fragment/grants를 만들지 않는다.
# - 앱 StateRef는 모르는 접두사를 조각으로 간주하므로 visit:/bonus: 같은 상태 금지.
# - S7 D6는 별도 paths 필드가 아니라 listen 선택지 + 선택별 action 메타로 표현.
# 구현일: 2026-07-30 | 작성: pjh (node-schema-gen/pjh/v1)
# ============================================================
from __future__ import annotations

import copy
import hashlib
import re
from collections.abc import Iterable
from typing import Any


# ── 닫힌 어휘 (명세 2절 — 코드가 잠그는 정적 구조) ─────────────────────

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
    # M4·M6(spot)은 제약표상 단독 플레이 전략이 없다 → infer_motivations()가
    # 보조 동기(M1 등)를 반드시 짝지어 플레이 가능성을 보장한다.
    "M5": "S2_HUNT_GATHER",
    "M6": "S7_PATRONIZE",  # 식음 전용 — spot 선택 경로에서는 제외된다
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

# ① 미션 타입 결정 순서 — node_content.MISSION_CYCLE과 동일한 다양화 순서.
#    (node_content를 import하면 LLM 클라이언트가 import 시점에 뜨므로 상수만 미러링)
_MISSION_ORDER: tuple[str, ...] = (
    "HUNT", "RESTORE_AR", "PHOTO_FIND", "PATH_TRACE",
    "COLLECT", "DIALOGUE_FIND", "FIND", "QUIZ_FIND",
)

# 단서설계규칙.md 예시 열 — derive가 재료 부족으로 유도 못 할 때의 폴백 풀.
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

# ── 휴리스틱 폴백용 키워드 (③ — 1차 분류는 LLM, 이건 실패 시 안전망) ──────
# 폴백 원칙: 코드가 확신할 수 있는 것만 본다 — cat 코드(닫힌 값) 우선, overview
# 키워드는 cat 코드가 없을 때만 보조로 참조하고, 한 글자 키워드는 쓰지 않는다
# ("산책/재산"의 '산', "건강"의 '강' 같은 부분문자열 오탐 — 인사동 실측으로 확인).

_THREAT_KEYWORDS = (
    "위협", "침입", "훼손", "파괴", "공격", "먹그림자", "망각귀", "요괴", "소탕",
)
_LOSS_KEYWORDS = (
    "분실", "잃어버", "잃은", "사라진", "유실", "도난", "되찾", "행방",
)
# 역사 서술(과거형·복원 완료) 문맥이면 위협/분실 오버라이드를 끈다.
_RESTORED_KEYWORDS = (
    "복원", "중건", "재건", "복구", "재현", "되살", "다시 세우", "다시 지어",
    "되찾았", "돌아왔",
)
_MARKET_KEYWORDS = ("시장", "상점", "상가", "장터", "쇼핑", "골목상권", "먹거리")
_NATURE_KEYWORDS = ("산책로", "등산로", "숲길", "계곡", "수목원", "강변", "하천", "생태", "자연경관", "국립공원")
_HERITAGE_KEYWORDS = ("궁궐", "고궁", "사찰", "유적", "문화재", "고택", "한옥", "성곽", "비석", "서원", "향교")
_PERSON_KEYWORDS = ("대왕", "장군", "선생", "위인", "업적", "생가", "기념관", "동상")
_MESSAGE_KEYWORDS = ("전언", "부탁", "미련", "기원", "추모", "편지", "전하다")
_TONE_MARKERS = ("니라", "허허", "거라", "구나", "로다", "느니")

# TourAPI KorService contenttypeid — 실제 코드표 기준(32=숙박이므로 매핑 제외).
#   12 관광지 · 14 문화시설 · 15 축제공연행사 · 25 여행코스 · 28 레포츠 · 38 쇼핑 · 39 음식점

# ── ⑤ NPC 합성(8-B) 모티프 테이블 ─────────────────────────────────────

_NPC_MOTIFS: dict[str, tuple[tuple[str, str], ...]] = {
    # 테마: ((이름 접두, 모티프 표기), ...)
    "heritage": (("먹", "붓·먹"), ("기와", "기와·처마"), ("현판", "현판·글씨")),
    "nature": (("솔", "솔잎·바람"), ("이끼", "이끼·바위"), ("물안개", "물·안개")),
    "market": (("엽전", "엽전·장부"), ("됫박", "됫박·저울"), ("보따리", "보따리·장터")),
    "food": (("가마솥", "가마솥·김"), ("찻잔", "찻잔·온기"), ("숯불", "숯불·연기")),
    "leports": (("바람", "바람·날개"), ("징검", "징검돌·걸음")),
    "festival": (("탈", "탈·풍물"), ("등불", "등불·잔치")),
    "person": (("수문", "갑주·깃발"), ("서책", "서책·벼루")),
}


class NodeContractError(ValueError):
    """app-v3-back의 QuestNode 계약을 위반한 경우."""


# ── ③ 동기 추론 (휴리스틱 폴백 — 1차는 node_content.classify_motivations) ──

def infer_motivations(
    source: dict[str, Any],
    *,
    is_food: bool = False,
    is_finale: bool = False,
) -> list[str]:
    """TourAPI 메타(ctid·cat 코드)와 overview 키워드로 동기 1~2개를 결정한다.

    규칙:
    - 위협/분실 키워드는 **보조 오버라이드**: 복원·중건 등 역사 서술 문맥이면 미발동,
      발동해도 기본(카테고리) 동기를 뒤에 유지한다 — "경복궁: 임진왜란 때 파괴" 오분류 방지.
    - M4(자연)·M6(상권 spot)은 단독으로 플레이 전략이 없으므로 항상 M1을 짝지운다.
    - 어떤 입력도 실패하지 않는다 — 최후 폴백 M1.
    """
    if is_food or _content_type_id(source) == 39 or _cat_prefix(source, "A05"):
        return ["M6"]

    text = _source_text(source)
    base = _base_motivations(source, text, is_finale=is_finale)

    restored = any(keyword in text for keyword in _RESTORED_KEYWORDS)
    override: str | None = None
    if not restored:
        if any(keyword in text for keyword in _LOSS_KEYWORDS):
            override = "M8"
        elif any(keyword in text for keyword in _THREAT_KEYWORDS):
            override = "M2"

    motivations = ([override] if override else []) + base
    if not motivations:
        motivations = ["M1"]
    motivations = _unique(motivations)[:2]

    # 플레이 가능성 보장 — 허용 전략(spot에선 S7 제외)이 하나도 없으면 M1을 짝지운다.
    if not _playable_strategies(motivations, is_food=is_food, is_finale=is_finale):
        motivations = _unique([motivations[0], "M1"])[:2]
    return motivations


def _base_motivations(source: dict[str, Any], text: str, *, is_finale: bool) -> list[str]:
    """카테고리 기반 기본 동기 — 오버라이드가 있어도 유지된다.

    판별 우선순위: ctid·cat 코드(닫힌 값) → overview 키워드(cat 코드가 아예 없을 때만).
    인사동 실측: cat1=A02(인문)인데 overview의 "산책"이 자연으로 오탐 → 코드 우선으로 차단.
    """
    motivations: list[str] = []
    ctid = _content_type_id(source)
    cat_nature = _cat_prefix(source, "A01")
    cat_human = _cat_prefix(source, "A02")
    cat_leports = _cat_prefix(source, "A03")
    cat_shop = _cat_prefix(source, "A04")
    no_cat = not (cat_nature or cat_human or cat_leports or cat_shop)

    if is_finale:
        motivations.append("M3")

    if ctid == 38 or cat_shop or (no_cat and any(k in text for k in _MARKET_KEYWORDS)):
        motivations.extend(["M6", "M1"])          # 상권 spot: M6 단독은 S7(식음 전용)뿐 → M1 동반
    elif cat_nature or (no_cat and any(k in text for k in _NATURE_KEYWORDS)):
        motivations.extend(["M4", "M1"])          # 자연: M4 단독은 전략 없음 → M1 동반
    elif ctid == 15:
        motivations.extend(["M4", "M6"])
    elif ctid == 14:
        motivations.extend(["M1", "M7"])
    elif ctid in {25, 28} or cat_leports:
        motivations.append("M7")
    else:
        if any(k in text for k in _PERSON_KEYWORDS):
            motivations.append("M3")
        if any(k in text for k in _MESSAGE_KEYWORDS):
            motivations.append("M9")
        if ctid == 12 or cat_human or any(k in text for k in _HERITAGE_KEYWORDS):
            motivations.append("M1")
    return motivations


# ── 전략 제약 검증 · 선택 ────────────────────────────────────────────

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


def _playable_strategies(
    motivations: Iterable[str], *, is_food: bool, is_finale: bool
) -> list[str]:
    """이 동기 조합으로 실제 컴파일 가능한 전략들. ② spot 노드는 S7 제외."""
    out: list[str] = []
    for strategy in STRATEGY_TO_MOTIVATIONS:
        if not is_food and strategy == "S7_PATRONIZE":
            continue
        if strategy_is_valid(strategy, motivations, is_finale=is_finale):
            out.append(strategy)
    return out


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

    # 명세의 빈 교집합(M4 단독 등)이 외부에서 주입돼도 생성은 중단하지 않는다.
    return "S1_TALK_GATHER"


def select_mission_type(
    motivations: list[str],
    stone_index: int,
    *,
    is_finale: bool = False,
    is_food: bool = False,
) -> str | None:
    """① 동기가 허용하는 전략에 대응하는 미션 타입만 순환 배정한다.

    generator가 **콘텐츠 생성 전에** 호출 — 미션 텍스트(LLM)와 액션 시퀀스가
    같은 전략을 가리키게 만드는 지점. 식음은 미션 없음(None), 피날레는 복원 고정.
    """
    if is_food:
        return None
    if is_finale:
        return "DIALOGUE_COLLECT"

    playable = set(_playable_strategies(motivations, is_food=False, is_finale=False))
    allowed_types = [
        mtype for mtype in _MISSION_ORDER
        if any(s in playable for s in MISSION_TO_STRATEGIES.get(mtype, ()))
    ]
    if not allowed_types:                     # 방어 — M1 폴백과 동일한 최후 안전망
        allowed_types = ["PHOTO_FIND"]
    return allowed_types[max(0, stone_index) % len(allowed_types)]


def select_strategies(
    motivations: list[str],
    mission_type: str | None,
    *,
    is_food: bool = False,
    is_finale: bool = False,
) -> list[str]:
    """미션 타입의 전략 후보 중 **제약표에 맞는 것만** 채택한다.

    v3: 부적합 후보를 다른 전략으로 리롤해 끼워 넣지 않는다 — 미션 콘텐츠와 무관한
    전략이 섞이면 액션·텍스트가 어긋나기 때문. 유효 후보가 없을 때만 동기 기본
    전략 1개로 폴백한다(select_mission_type을 거쳤다면 도달하지 않는 경로).
    """
    if is_food:
        return ["S7_PATRONIZE"]
    if is_finale:
        return ["S6_ACCUMULATE"]

    selected = [
        candidate
        for candidate in MISSION_TO_STRATEGIES.get(mission_type or "", ())
        if candidate != "S7_PATRONIZE"                      # ② 식음 전용
        and strategy_is_valid(candidate, motivations)
    ][:2]
    if selected:
        return selected

    for strategy in _playable_strategies(motivations, is_food=False, is_finale=False):
        return [strategy]
    return [reroll_strategy("S1_TALK_GATHER", motivations)]


# ── ⑤ NPC 합성 (8-B) ────────────────────────────────────────────────

def synthesize_npc(
    source: dict[str, Any],
    motivations: list[str],
    *,
    is_food: bool = False,
    is_finale: bool = False,
) -> dict[str, Any]:
    """장소 메타 → 도깨비 NPC(이름·archetype·motif·speech·motivation).

    결정적(sha256 seed) — 같은 장소는 항상 같은 도깨비. 문구가 아닌 **정체성 필드**라
    코드 고정 영역이다(대사 문구는 여전히 LLM 슬롯).
    """
    text = _source_text(source)
    if is_food or _content_type_id(source) == 39:
        theme = "food"
    elif _content_type_id(source) == 15:
        theme = "festival"
    elif _content_type_id(source) in {25, 28} or _cat_prefix(source, "A03"):
        theme = "leports"
    elif _content_type_id(source) == 38 or _cat_prefix(source, "A04") or any(
        k in text for k in _MARKET_KEYWORDS
    ):
        theme = "market"
    elif _cat_prefix(source, "A01") or any(k in text for k in _NATURE_KEYWORDS):
        theme = "nature"
    elif any(k in text for k in _PERSON_KEYWORDS):
        theme = "person"
    else:
        theme = "heritage"

    pool = _NPC_MOTIFS[theme]
    seed = str(source.get("node_id") or source.get("name") or "")
    digest = hashlib.sha256(f"npc|{seed}".encode("utf-8")).digest()
    prefix, motif = pool[digest[0] % len(pool)]

    return {
        "name": "수호 도깨비" if is_finale else f"{prefix} 도깨비",
        "archetype": "guardian" if is_finale else "persona",
        "motif": motif,
        "speech": "~니라, 허허",
        "motivation": "+".join(motivations),   # 앱은 npc.motivation("M1+M7")도 파싱
    }


# ── 노드 확장 본체 ───────────────────────────────────────────────────

def enrich_quest(
    quest: dict[str, Any],
    source: dict[str, Any],
    *,
    motivations: list[str] | None = None,
) -> dict[str, Any]:
    """기존 퀘스트에 app-v3-back QuestNode 확장 필드를 붙인다.

    motivations를 넘기면(generator의 LLM 분류 결과) 그대로 쓰고,
    없으면 휴리스틱으로 추론한다(테스트·단독 호출 하위호환).
    """
    out = copy.deepcopy(quest)
    is_food = _is_food(out)
    is_finale = bool(out.get("is_finale"))
    mission = out.get("mission") if isinstance(out.get("mission"), dict) else {}

    motivations = list(motivations) if motivations else infer_motivations(
        source, is_food=is_food, is_finale=is_finale
    )
    strategies = select_strategies(
        motivations,
        str(mission.get("type") or ""),
        is_food=is_food,
        is_finale=is_finale,
    )

    out["motivation"] = motivations
    if not isinstance(out.get("npc"), dict) or not out.get("npc", {}).get("name"):
        out["npc"] = synthesize_npc(source, motivations, is_food=is_food, is_finale=is_finale)
    out["strategy"] = strategies
    out["actions"] = compile_actions(out, strategies)
    out["hint_ladder"] = build_hint_ladder(out)
    out["requires"] = _string_list(out.get("requires"))
    out["requires_mode"] = str(out.get("requires_mode") or "none")
    out["grants"] = build_base_grants(out)
    out["clue"] = _clean_optional_string(out.get("clue"))
    out["success"] = build_success(out["actions"], is_food=is_food)

    # 식음 오인 방지: 앱의 effectiveGrants와 StateRef 파서 모두에서 조각이 되지 않게 강제.
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
        # D6: paths라는 별도 DTO를 만들지 않고 앱이 이미 파싱하는 choices와 raw action 메타 사용.
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
    atoms = _dedupe_and_order_atoms(atoms)

    # ② 가드 — 어떤 경로로든 플레이 원자가 0개면 빈 노드가 되지 않게 S1 수집으로 보강.
    if not atoms:
        mission = quest.get("mission") if isinstance(quest.get("mission"), dict) else {}
        atoms = [{"a": "tap", "target": str(mission.get("find") or "글씨파편"), "count": [0, 1]}]

    actions.extend(atoms)
    actions.append({"a": "report", "npc": _npc_name(quest)})
    return actions


def build_choices(quest: dict[str, Any], *, is_food: bool) -> list[dict[str, Any]]:
    """ActionChoice가 파싱하는 키(id/text/flags/affinity/reward_mod)만 사용한다.

    문구는 LLM 슬롯 대상(#31)이지만, 앱이 text를 그대로 렌더하므로 빈 값 대신
    범용 폴백 문구를 넣는다 — 효과(flags/affinity/reward_mod)는 코드 고정(규칙 2조).
    """
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
        elif atom == "purchase" and action.get("optional"):
            success.append("one_of:purchase_verified|tap_done")
    return _unique(success)


# ── ④ 단서 체인 — 이름은 다음 노드의 수행 조건에서 유도 + 유일성 보장 ────

_HANJA_NUM = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八", 9: "九"}
_CHOSEONG = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"


def _choseong_of(text: str) -> str | None:
    """정답 첫 글자의 초성(단서설계규칙 S3: '자음/모음/한자/숫자')."""
    for ch in text:
        code = ord(ch)
        if 0xAC00 <= code <= 0xD7A3:
            return _CHOSEONG[(code - 0xAC00) // 588]
        if ch.isdigit():
            return _HANJA_NUM.get(int(ch))
        if ch.strip():
            return ch
    return None


def derive_clue_name(target: dict[str, Any], used: set[str] | None = None) -> str:
    """단서설계규칙.md 준수 — "단서가 실제 수행 조건으로 쓰임".

    다음 노드(target)의 전략별로 이름이 알려줘야 하는 것을 미션 데이터에서 유도:
    - S2 요괴 수 → 五影 / - S3 정답 일부 → 초성·한자 / - S4 발자국 수·대상 → 대문 三보
    - S5 촬영 대상 → 현판 / - S6 개수 → 三片 / - S1 전언 키워드
    유도 재료가 없으면 규칙 문서의 예시 풀에서 결정적으로 선택. `used`로 시나리오 내
    유일성을 보장한다(충돌 시 풀 순회 → 숫자 접미).
    """
    used = used or set()
    strategy = _first_strategy(target)
    mission = target.get("mission") if isinstance(target.get("mission"), dict) else {}
    quiz = target.get("quiz") if isinstance(target.get("quiz"), dict) else {}

    derived: str | None = None
    if strategy == "S2_HUNT_GATHER":
        count = _safe_int(mission.get("count"), default=0)
        if count and count in _HANJA_NUM:
            derived = f"{_HANJA_NUM[count]}影"
    elif strategy == "S3_RIDDLE_UNLOCK":
        answer = _quiz_answer_text(quiz) or _quiz_answer_text(
            mission if "options" in mission else {}
        )
        derived = _choseong_of(answer) if answer else None
    elif strategy == "S4_PHOTO_TRAIL":
        steps = _string_list(mission.get("steps"))
        n = len(steps) or 3
        targets = _string_list(mission.get("photo_targets"))
        head = (targets[0][:2] if targets else "자취")
        if n in _HANJA_NUM:
            derived = f"{head} {_HANJA_NUM[n]}보"
    elif strategy == "S5_PHOTO_PROOF":
        targets = _string_list(mission.get("photo_targets"))
        if targets:
            derived = targets[0][:4]
    elif strategy == "S6_ACCUMULATE":
        items = _string_list(mission.get("items")) or _string_list(mission.get("parts"))
        count = len(items) or _safe_int(mission.get("count"), default=0)
        if count and count in _HANJA_NUM:
            derived = f"{_HANJA_NUM[count]}片"
    elif strategy == "S1_TALK_GATHER":
        find = _clean_optional_string(mission.get("find"))
        if find:
            derived = f"{find[:2]} 전언"

    candidates: list[str] = []
    if derived:
        candidates.append(derived[:5].strip())
    pool = CLUE_NAMES_BY_STRATEGY.get(strategy) or CLUE_NAMES_BY_STRATEGY["S1_TALK_GATHER"]
    seed = str(target.get("node_id") or "")
    digest = hashlib.sha256(f"{strategy}|{seed}".encode("utf-8")).digest()
    candidates.extend(pool[(digest[0] + i) % len(pool)] for i in range(len(pool)))

    for name in candidates:
        if name and name not in used:
            return name
    base = candidates[0] or "단서"
    n = 2
    while f"{base}·{n}" in used:
        n += 1
    return f"{base}·{n}"


def choose_clue_name(target_strategy: str, seed: str) -> str:
    """(하위호환) 전략 풀에서 결정적 선택 — 신규 경로는 derive_clue_name 사용."""
    candidates = CLUE_NAMES_BY_STRATEGY.get(target_strategy) or CLUE_NAMES_BY_STRATEGY["S1_TALK_GATHER"]
    digest = hashlib.sha256(f"{target_strategy}|{seed}".encode("utf-8")).digest()
    return candidates[digest[0] % len(candidates)]


def link_state_graph(node_sequence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """단서 체인과 피날레 requires를 앱 상태 그래프 형식으로 연결한다.

    - 식음 노드는 현재 앱의 stone chapter 목록에서 제외되므로 핵심 단서 체인에 넣지 않는다.
    - path_id=b1 샛길은 본선 대체 경로이므로 피날레 전량 requires에 넣지 않는다.
    - 분기 트리의 세부 보상 동치화는 #24 route_tree 담당 범위이며, 여기서는 본선 계약을 보존한다.
    - v3: 단서 이름은 다음 노드의 수행 조건에서 유도(derive_clue_name), 시나리오 내 유일.
    """
    sequence = copy.deepcopy(node_sequence)
    main_stones = [
        node
        for node in sequence
        if not _is_food(node) and str(node.get("path_id") or "main") == "main"
    ]
    non_finale = [node for node in main_stones if not node.get("is_finale")]
    finale = next((node for node in reversed(main_stones) if node.get("is_finale")), None)

    used_clues: set[str] = set()
    for current, target in zip(non_finale, main_stones[1:]):
        clue = derive_clue_name(target, used_clues)
        used_clues.add(clue)
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


# ── 계약 검증 · QA ───────────────────────────────────────────────────

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

    # ② 비식음 노드는 최소 1개의 플레이 원자를 가져야 한다(빈 노드=공짜 조각 금지).
    play_atoms = {"answer", "capture", "tap", "defeat", "follow", "purchase", "combine"}
    if not _is_food(node) and not any(
        isinstance(a, dict) and a.get("a") in play_atoms for a in actions
    ):
        raise NodeContractError("비식음 노드에 플레이 액션이 없습니다(공짜 조각 금지).")

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
    """정답 유출·말투·grounding 범위를 자동 점검한다. 응답 DTO에는 넣지 않는다.

    v3: 환각 체크는 조사(助詞)를 스트리핑한 어간 비교 — 한국어 곡용 오탐 완화.
    여전히 휴리스틱이므로 게이트가 아니라 **경고 로그**용이다(generator에서 배선).
    """
    quiz = node.get("quiz") if isinstance(node.get("quiz"), dict) else {}
    answer = _quiz_answer_text(quiz)
    ladder = node.get("hint_ladder") if isinstance(node.get("hint_ladder"), dict) else {}
    hint_text = " ".join(str(ladder.get(key) or "") for key in ("H1", "H2", "H3"))
    dialogue = str(node.get("npc_dialogue") or "")
    overview = str(source.get("overview") or "")

    answer_leak = bool(answer and answer in hint_text)
    tone_ok = not dialogue or any(marker in dialogue for marker in _TONE_MARKERS)

    claim_stems = {_stem(t) for t in _meaningful_tokens(dialogue)}
    ground_stems = {
        _stem(t) for t in _meaningful_tokens(f"{source.get('name', '')} {source.get('title', '')} {overview}")
    }
    unsupported = sorted(
        stem
        for stem in claim_stems
        if len(stem) >= 3 and not _stem_supported(stem, ground_stems)
    )[:10]

    return {
        "answer_leak": answer_leak,
        "tone_ok": tone_ok,
        # 어간 3개 이상이 근거 밖일 때만 플래그 — 문체 어휘로 인한 소음 하한.
        "hallucination_flag": bool(overview) and len(unsupported) >= 3,
        "unsupported_tokens": unsupported,
        "contract_ok": _contract_ok(node),
    }


# ── 전략 컴파일 ─────────────────────────────────────────────────────

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
    if strategy == "S7_PATRONIZE":
        # ② 안전망 — 선택 경로상 spot에 S7이 오지 않지만, 외부 주입 시에도 빈 노드 금지.
        return [
            {"a": "purchase", "menu": f"{name} 한 상", "optional": True, "verification": "receipt"},
            {"a": "tap", "target": fragment_target, "count": [0, 1]},
        ]
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
        "correct": {"exp": 30, "coupon": 200},   # 명세 6-1 예시 정합(보상 증폭은 보너스만)
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
    priority = {
        "answer": 10, "purchase": 15, "capture": 20,
        "follow": 30, "defeat": 30, "tap": 40, "combine": 50,
    }
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


# ── 내부 헬퍼 ───────────────────────────────────────────────────────

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


def _cat_prefix(source: dict[str, Any], prefix: str) -> bool:
    """TourAPI cat 코드(A01xx…) 프리픽스 매칭 — ③ 이슈의 'cat→기본동기' 절반."""
    for key in ("cat1", "cat", "cat2", "cat3", "category"):
        value = source.get(key)
        if isinstance(value, str) and value.strip().upper().startswith(prefix):
            return True
    return False


def _source_text(source: dict[str, Any]) -> str:
    parts = [
        source.get("name"),
        source.get("title"),
        source.get("overview"),
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


# ── QA 토큰 처리(⑥) — 한국어 조사 스트리핑 어간 비교 ─────────────────────

# 세계관·퀘스트 상용어는 장소 grounding 대상이 아니다(고정 템플릿 대사 오탐 방지).
_STOPWORDS = {
    "그리고", "하지만", "이곳", "여기", "도깨비", "기억석", "조각", "허허",
    "기억", "흔적", "임무", "지령", "복원", "흩어진", "마지막", "조각이로",
    "복원하거", "찾아보거", "살펴보거", "모아", "숨었느니", "오호",
}
_PARTICLES = (
    "에서는", "에게서", "으로써", "이라는", "라는", "이나", "이며", "이다",
    "에서", "에게", "께서", "부터", "까지", "으로", "은", "는", "이", "가",
    "을", "를", "의", "에", "와", "과", "도", "만", "로", "라", "다", "요",
)


def _meaningful_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", text)
        if token not in _STOPWORDS
    }


def _stem(token: str) -> str:
    """가장 긴 조사 접미 1개를 떼어낸 어간(최소 2글자 유지)."""
    for particle in _PARTICLES:  # 긴 것부터 정렬돼 있음
        if token.endswith(particle) and len(token) - len(particle) >= 2:
            return token[: -len(particle)]
    return token


def _stem_supported(stem: str, ground_stems: set[str]) -> bool:
    """어간이 근거 어간과 접두 일치(≥2글자)하면 지지된 것으로 본다."""
    if stem in ground_stems:
        return True
    return any(
        g.startswith(stem) or stem.startswith(g)
        for g in ground_stems
        if len(g) >= 2
    )


def _contract_ok(node: dict[str, Any]) -> bool:
    try:
        validate_app_contract(node)
    except NodeContractError:
        return False
    return True