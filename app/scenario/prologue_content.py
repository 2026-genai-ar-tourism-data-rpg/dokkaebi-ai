# ============================================================
# [v1] 코스 오프닝 프롤로그 생성 — 지역·첫 장소 grounding (생성 시 1회)
# pipeline: AI 백엔드 / 시나리오 (고정 콘텐츠 = 코스당 프롤로그 1개)
# 구현(요약): 화자 순서·연출 비트(beat) 위치는 앱 프롤로그 화면의 고정 스켈레톤을 그대로
#            따르고, 대사 텍스트만 실제 region·첫 조각 장소로 LLM이 새로 쓴다
#            (node_content.py의 '구조 고정 JSON, 텍스트만 채움' 패턴과 동일).
#            실패/비활성/mock이면 원래 종로 대본에서 지역명만 치환한 고정 스크립트로 폴백
#            — 항상 스켈레톤과 같은 줄 수를 보장한다.
# 구현일: 2026-09-04 | 작성: Claude (prologue-story-gen/claude/v1)
# ============================================================
import json

from app.core.logger import get_logger
from app.llm.client import get_llm

logger = get_logger(__name__)
_llm = get_llm()

# 앱 prologue_screen.dart의 _lines와 1:1 — 화자 순서·beat 위치는 여기서 고정한다.
# speaker: narration | npc | player | beat. beat는 텍스트 없음(연출 트리거만).
_SKELETON = [
    {"speaker": "narration"}, {"speaker": "narration"}, {"speaker": "narration"}, {"speaker": "narration"},
    {"speaker": "beat", "beat": "reach"},
    {"speaker": "narration"},
    {"speaker": "beat", "beat": "reveal"},
    {"speaker": "narration"}, {"speaker": "narration"}, {"speaker": "narration"}, {"speaker": "narration"},
    {"speaker": "beat", "beat": "recoil"},
    {"speaker": "narration"},
    {"speaker": "npc"},
    {"speaker": "player"},
    {"speaker": "narration"},
    {"speaker": "npc"},
    {"speaker": "beat", "beat": "longing"},
    {"speaker": "narration"},
    {"speaker": "npc"},
    {"speaker": "narration"},
    {"speaker": "npc"},
    {"speaker": "narration"}, {"speaker": "narration"},
]
# 텍스트가 필요한 슬롯의 (스켈레톤 인덱스, 화자) — LLM은 이 순서로 문장만 채운다.
_TEXT_SLOTS = [(i, s["speaker"]) for i, s in enumerate(_SKELETON) if s["speaker"] != "beat"]

_ROLE_LABEL = {"narration": "내레이션", "npc": "NPC(수호 도깨비)", "player": "플레이어"}

_PLOT = (
    "너는 한국 전통 설화풍 AR 게임 '도깨비'의 오프닝 대본 작가다.\n"
    "고정 설정(바꾸지 마라): 망각귀가 이 땅의 기억석을 깨뜨렸다. 플레이어는 우연히 깨진 기억석의 푸른 빛을 "
    "보고 도깨비눈이 뜨여, 인간이 못 보는 도깨비들을 보게 된다. 작은 초롱을 든 수호 도깨비가 나타나 "
    "플레이어에게 흩어진 기억석 조각을 모아달라는 첫 의뢰를 건넨다. "
    "도깨비 말투는 '~느니라/~거라/허허' 같은 예스러운 반존대.\n"
    "이 이야기의 무대는 '{region}'이고, 플레이어가 처음 찾아갈 곳은 '{first_name}'이다 — 이 두 정보를 "
    "내레이션 어딘가에 자연스럽게 녹여라(장소를 인위적으로 나열하지 말 것).\n"
    "플레이어 이름 자리는 채우지 말고 리터럴 문자열 {{name}}을 그대로 남겨라(다른 시스템이 나중에 치환한다).\n"
)
_FORMAT = (
    "아래 {n}개 대사 슬롯을 순서대로, 화자에 맞게 채워라(각 1~2문장, 짧게):\n{roles}\n"
    '다른 말 없이 아래 JSON만 출력: {{"lines": ["<슬롯1 텍스트>", "<슬롯2 텍스트>", "..."]}} (배열 길이 = {n})'
)

# 폴백(A안): 원래 종로 고정 대본에서 지역명만 반영. LLM 실패해도 항상 이 24줄을 보장한다.
_FALLBACK_TEXTS = [
    "{name}는 {region} 부근을 지나던 평범한 사람이다.",
    "오래된 골목길을 걷던 중, 낡은 담장 아래에서 희미하게 흔들리는 푸른빛을 발견한다.",
    "처음에는 누군가 떨어뜨린 조명이나 반사광이라고 생각한다.",
    "하지만 빛은 가까이 다가갈수록 점점 또렷해지고, 마치 살아 있는 것처럼 골목 안쪽으로 흘러간다.",
    "사람들의 발걸음은 느려지고, 익숙하던 거리는 낯선 모습으로 바뀐다.",
    "오래된 처마 밑에 웅크린 작은 도깨비. 깨진 돌 조각 주변을 맴도는 푸른 불씨.",
    "검은 안개에 휘감겨 힘없이 떠도는 도깨비 영혼들.",
    "그들은 무언가를 잃어버린 듯 같은 자리를 맴돌고 있다.",
    "몇몇은 망각귀에게 당해 이름도, 자신이 지키던 장소도 잊어가고 있다.",
    "그때, 작은 초롱을 든 도깨비 하나가 {name} 앞에 나타난다.",
    "드디어… 우리를 볼 수 있는 인간이 나타났구나.",
    "너희 뭐야? 왜 나한테 이런 게 보이는 거야?",
    "도깨비는 깨진 기억석 조각을 가리킨다.",
    "네가 본 것은 기억의 빛이니라. 망각귀가 이 땅의 기억석을 깨뜨렸고, 그 빛이 네 눈에 깃들었다. "
    "이제 너는 인간들이 잊어버린 것들을 보게 되었느니라.",
    "도깨비는 잠시 침묵하다가 대답한다.",
    "돌아갈 방법은 있다. 흩어진 기억석 조각을 모아 망각귀의 봉인을 되살리면, 네 눈에 깃든 도깨비의 기운도 거두어 주마.",
    "그리고 도깨비는 {name}에게 첫 번째 의뢰를 건넨다.",
    "탐사자여, 두렵겠지만 우리를 도와다오. 이곳의 기억이 완전히 사라지기 전에, 첫 번째 조각을 찾아야 하느니라.",
    "이 순간부터 {name}는 탐사자가 된다.",
    "처음에는 평범한 인간으로 돌아가기 위해. 하지만 점점, 잊혀진 장소의 기억을 되살리기 위해.",
]


def _role_note() -> str:
    return "\n".join(f"{i + 1}번: {_ROLE_LABEL[speaker]}" for i, (_, speaker) in enumerate(_TEXT_SLOTS))


def _json(raw: str) -> dict | None:
    try:
        return json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except Exception:
        return None


def _merge(texts: list[str]) -> list[dict]:
    """텍스트 슬롯 채운 결과를 스켈레톤에 도로 끼워 24줄 전체를 만든다."""
    by_index = {i: t for (i, _speaker), t in zip(_TEXT_SLOTS, texts)}
    lines = []
    for i, slot in enumerate(_SKELETON):
        if slot["speaker"] == "beat":
            lines.append({"speaker": "beat", "text": "", "beat": slot["beat"]})
        else:
            lines.append({"speaker": slot["speaker"], "text": by_index[i], "beat": None})
    return lines


def fallback_prologue(region: str, first_name: str) -> list[dict]:
    """LLM 미사용 경로(with_dialogue=False)·생성 실패 공용 폴백. 원래 종로 고정 대본에서
    지역명만 반영 — 언제나 스켈레톤과 같은 24줄을 보장한다."""
    texts = [t.format(name="{name}", region=region) for t in _FALLBACK_TEXTS]
    return _merge(texts)


async def generate_prologue(region: str, first_node: dict | None) -> list[dict]:
    """코스 오프닝 프롤로그 생성. 화자 순서·beat는 고정, 대사만 region·첫 장소로 새로 쓴다.
    실패/비JSON/슬롯 수 불일치면 지역명만 반영한 고정 대본으로 폴백(항상 24줄 보장)."""
    first_name = (first_node or {}).get("name") or region
    fallback = fallback_prologue(region, first_name)
    prompt = _PLOT.format(region=region, first_name=first_name) + _FORMAT.format(
        n=len(_TEXT_SLOTS), roles=_role_note()
    )
    try:
        raw = await _llm.generate(prompt)
        data = _json(raw) or {}
        lines = data.get("lines")
        if not isinstance(lines, list) or len(lines) != len(_TEXT_SLOTS):
            raise ValueError(f"슬롯 수 불일치(기대 {len(_TEXT_SLOTS)}, 실제 {lines!r})")
        texts = [str(t).strip() for t in lines]
        if any(not t for t in texts):
            raise ValueError("빈 슬롯 존재")
    except Exception as e:
        logger.warning("프롤로그 생성 실패(지역=%s) → 지역명 치환 폴백: %s", region, e)
        return fallback
    return _merge(texts)
