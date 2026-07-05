# ============================================================
# [v1] 분기 대화 서비스 — 선택지 + 연계(인벤토리) + 종료 (기획 8-D·7-C)
# pipeline: AI 백엔드 / 서빙 (찐 RPG 대화: 동적 생성, 구조적 종료)
# 구현(요약): 노드 grounding + 인벤토리·history 주입 → LLM이 대사+선택지(2) 생성.
#            'collect' 선택 또는 깊이상한(turn>=max) → 조각 grants + done. 항상 수렴.
# 구현일: 2026-06-19 | 작성: kys (rpg-dialogue/kys/v1)
# ============================================================
import json

from app.config import get_settings
from app.core.logger import get_logger
from app.llm.client import LLMClient
from app.region.memory_cache import get_region_cache
from app.tourapi.client import TourAPIClient

logger = get_logger(__name__)

_llm = LLMClient()
_tour = TourAPIClient()
_TONE = "도깨비 말투(어미 '~니라/~겠느냐', 감탄 '허허'), 2~3문장, 군더더기·메타설명 금지."


async def _grounding(node_id: str, node_name: str) -> str:
    """대사 근거 텍스트 확보: 지역캐시 → (미스) detailCommon2 → 이름."""
    ctx = get_region_cache().get_text(node_id)
    if ctx:
        return ctx
    if node_id.startswith("tour_"):
        detail = await _tour.detail_common(node_id.split("_", 1)[1])
        if detail and detail.get("overview"):
            return detail["overview"]
    return node_name or ""


def _inventory_text(inventory: dict | None) -> str:
    """연계: 지금까지 모은 단서·조각을 프롬프트용 문장으로."""
    items = (inventory or {}).get("items") or []
    return "지금까지 모은 것: " + ", ".join(map(str, items)) if items else "아직 모은 것이 없다."


async def run_branching(
    *, node_id: str, node_name: str = "", region_id: str = "",
    history: list[dict] | None = None, inventory: dict | None = None,
    last_choice: str | None = None, turn: int = 0, fragment_id: str | None = None,
) -> dict:
    """[분기 대화] 한 턴 생성. 반환 {response, choices[], grants[], done}.

    'collect' 선택 또는 turn>=max_dialogue_turns 면 조각 획득+done(수렴). 그 외엔 대사+선택지.
    담당: 상태머신·종료 = 김예슬 / 선택지·프롬프트 품질 = 박준형.
    """
    s = get_settings()
    ctx = await _grounding(node_id, node_name)
    inv = _inventory_text(inventory)
    done = last_choice == "collect" or turn >= s.max_dialogue_turns

    if done:
        # 대화 마무리 = "퀘스트 수령 + 힌트" (조각 획득 X — 그건 AR 탐색 단계 QUEST_ACTIVE)
        prompt = (
            f"너는 '{node_name}'을(를) 지키는 도깨비다.\n[장소 정보] {ctx}\n[플레이어가 모은 것] {inv}\n"
            f"플레이어에게 이곳의 기억석 조각을 찾으라는 의뢰를 주고, **어디를 AR로 살펴봐야 할지 "
            f"장소 정보에 근거한 힌트**를 준다(예: 특정 건물·조형물 근처). {_TONE}"
        )
        line = await _llm.generate(prompt)
        # grants는 비움 — 조각은 AR 탐색(앱)에서 획득. done=대화 종료→탐색으로.
        return {"response": line, "choices": [], "grants": [], "done": True}

    hist = "\n".join(f"- {h.get('text', '')}" for h in (history or []))[-800:]
    prompt = (
        f"너는 '{node_name}'을(를) 지키는 도깨비 NPC다. 장소 역사에 근거해서만 말한다.\n"
        f"[장소 정보] {ctx}\n[플레이어가 모은 것] {inv}\n[지금까지 대화]\n{hist}\n"
        f"규칙: {_TONE} 그리고 플레이어가 고를 짧은 선택지 2개를 제안한다. "
        f"모은 단서가 있으면 그걸 언급해도 좋다.\n"
        f'반드시 아래 JSON만 출력: {{"line": "<대사>", "choices": ["<선택지1>", "<선택지2>"]}}'
    )
    raw = await _llm.generate(prompt)
    line, choices = _parse(raw)
    objs = [{"id": f"c{i}", "text": t} for i, t in enumerate(choices[:2])]
    objs.append({"id": "collect", "text": "의뢰를 받고 기억석을 찾아 나선다"})  # → AR 탐색으로
    return {"response": line, "choices": objs, "grants": [], "done": False}


def _parse(raw: str) -> tuple[str, list[str]]:
    """LLM 출력에서 {line, choices} JSON 추출. 실패 시 원문+기본 선택지로 폴백."""
    try:
        s = raw[raw.index("{"): raw.rindex("}") + 1]
        d = json.loads(s)
        line = (d.get("line") or "").strip() or raw.strip()
        ch = [c for c in (d.get("choices") or []) if isinstance(c, str) and c.strip()]
        return line, (ch or ["도깨비에게 더 물어본다", "주변을 둘러본다"])
    except Exception:
        return raw.strip(), ["도깨비에게 더 물어본다", "주변을 둘러본다"]
