# ============================================================
# [v1] 노드: persona_inject — 페르소나/진행상황 주입 + 캐시키 산출
# pipeline: AI 백엔드 / 오케스트레이션 그래프 (1번째 노드)
# 구현(요약): 시그니처 + 캐시키 산출 + LLM 페르소나 합성(노드당 1회, 캐시).
#            합성 규칙 = 기획_통합.md §8-B, 프롬프트 = 프롬프트_설계_v0.md §3-D.
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# 수정일: 2026-08-12 | persona 시드 로드 구현: 정찬희
# ------------------------------------------------------------
# [v2] 캐시 키에 프롬프트 버전 삽입 + 공용 LLM 클라이언트 사용.
# 구현(요약): 키가 `npc:{node}:{stage}`·`persona:{node}`라 프롬프트를 고쳐도 대사 1일·
#            페르소나 7일 동안 옛 출력이 나갔다(실측). config.prompt_version을 키에 넣어
#            프롬프트 개정과 캐시 무효화를 한 번에 묶는다.
# 구현일: 2026-08-19 | 작성: kys (dialogue-rework/kys/v1)
# ============================================================
import json

from app.config import get_settings
from app.core.cache import get_cache
from app.core.exceptions import LLMCallError
from app.core.logger import get_logger
from app.llm.client import get_llm
from app.pipeline.state import DialogueState
from app.region.memory_cache import get_region_cache

logger = get_logger(__name__)

_llm = get_llm()
_PERSONA_TTL_S = 60 * 60 * 24 * 7  # 장소 정보는 정적 → 장기 캐싱(노드당 1회 합성이 목표)
_FALLBACK_ARCHETYPE = "guardian"  # 모티프 추출 실패 시 기본값(기획_통합.md §16) — 어떤 장소에도 무난


async def persona_inject(state: DialogueState) -> dict:
    """[노드] NPC 페르소나·진행상황을 state에 주입하고 캐시키를 만든다.

    담당: 흐름/주입 시점 = 김예슬 / persona 시드 데이터 = 이지선 → LLM 합성 구현 = 정찬희.
    """
    node_id = state.get("node_id", "")
    stage = state.get("stage", "등장")
    version = get_settings().prompt_version
    persona = await _load_persona(node_id, state.get("node_name", ""))
    # 사용자 발화가 있으면 캐시를 쓰지 않는다(빈 키) — 질문이 달라도 같은 대사가 나가면
    # 되묻는 의미가 없다. 발화 없는 정형 대사(등장·완료 등)만 노드·stage로 캐싱한다.
    cache_key = "" if state.get("query") else f"npc:{version}:{node_id}:{stage}"
    return {"persona": persona, "cache_key": cache_key}


async def _load_persona(node_id: str, node_name: str) -> dict:
    """persona 시드 로드: 캐시 → (미스) LLM 합성(기획 8-B) → 캐시 저장. 노드당 1회 목표."""
    cache = get_cache()
    ckey = f"persona:{get_settings().prompt_version}:{node_id}"
    cached = await cache.get(ckey)
    if cached is not None:
        return json.loads(cached)

    persona = await _synthesize_persona(node_id, node_name)
    await cache.set(ckey, json.dumps(persona, ensure_ascii=False), _PERSONA_TTL_S)
    return persona


async def _synthesize_persona(node_id: str, node_name: str) -> dict:
    """LLM 페르소나 합성(기획_통합.md §8-B, 프롬프트 프롬프트_설계_v0.md §3-D).

    overview는 지역 캐시에서(미스 시 자체 재조회, region.memory_cache 처리).
    합성 실패(LLM 오류·JSON 파싱 실패) 시 guardian 기본값으로 진행(대화 자체는 안 막음).
    """
    overview = await get_region_cache().get_text(node_id) or ""
    title = node_name or node_id
    prompt = (
        "[시스템] 관광지 데이터를 도깨비 캐릭터로 변환. 규칙: 모티프 추출"
        "(① 대표인물 ② 상징물 ③ 기능 ④ 자연) → 아키타입(persona/guardian/trade/spirit).\n"
        f"[입력] title={title}, overview={overview}\n"
        '[출력] 아래 JSON만: {"name":"<○○ 도깨비>","archetype":"persona|guardian|trade|spirit",'
        '"motif":"<모티프>","persona":"<말투·성격 2문장>","appearance_tags":["<태그>"]}'
    )
    try:
        raw = await _llm.generate(prompt, temperature=0.3)  # 페르소나=사실 안정(프롬프트_설계_v0 §5)
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        if not (data.get("archetype") and data.get("persona")):
            raise ValueError("필수 필드(archetype/persona) 누락")
        return data
    except (LLMCallError, ValueError) as e:
        logger.warning("페르소나 합성 실패(%s) → %s 기본값 fallback: %s", node_id, _FALLBACK_ARCHETYPE, e)
        return {
            "name": f"{title} 도깨비",
            "archetype": _FALLBACK_ARCHETYPE,
            "motif": "",
            "persona": "이 장소를 오래도록 지켜온 과묵하고 위엄 있는 도깨비.",
            "appearance_tags": [],
        }
