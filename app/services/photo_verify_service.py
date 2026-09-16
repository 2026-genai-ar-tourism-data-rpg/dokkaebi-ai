# ============================================================
# [v1] 사진 검증 서비스 — 플레이어 사진이 그 장소의 그 타깃인지 비전 모델로 판정
# pipeline: AI 백엔드 / 서비스 (PHOTO_FIND·PATH_TRACE 촬영 미션의 완료 판정)
# 구현(요약): 실시간 AR은 ARKit(기기)이, 사진 판정은 여기(서버)가 한다 — 한 장에 한 번.
#   · 입력: 플레이어 사진(data URI) + TourAPI 참조 사진(photo_refs.ref_image) + 타깃명·별칭
#   · 비전 모델에 "첫 사진이 참조 사진들과 같은 대상인가, 글자가 보이면 읽어라"를 JSON으로 묻는다.
#     이미지 대 이미지 비교라 텍스트 설명("현판이 보이나")보다 훨씬 강하고, 한국 문화유산은
#     글자(現판·안내판·비석)가 많아 text_seen 일치가 사실상 확정 신호가 된다.
#   · 판정 = match ∧ (confidence ≥ 임계  ∨  읽은 글자가 타깃/장소/별칭과 일치)
#   · 모델 장애·파싱 실패는 mode="unverified"로 200 응답 — 플레이를 막지 않는다(앱은 '행위 완료'로
#     폴백). 502로 올리면 현장에서 셔터를 눌러도 진행이 안 된다.
#   · 결과를 도깨비 대사(npc_line)로도 돌려준다 — 검증이 곧 연출이 되게("興化門 세 글자가 선명하구나").
# 구현일: 2026-09-16 | 작성: kys (photo-verify/kys/v1)
# ============================================================
import json
import re
import time

from app.config import get_settings
from app.core.logger import get_logger
from app.llm.client import get_vision_llm

logger = get_logger(__name__)

_PROMPT = (
    "너는 한국 문화유산 사진을 대조하는 검수자다. 첫 번째 이미지는 플레이어가 지금 '{place}'에서 찍은 사진이고, "
    "그 뒤 {n_ref}장은 한국관광공사가 촬영한 '{target}'의 참조 사진이다.\n"
    "판단할 것: 첫 번째 사진에 '{target}'(다른 이름: {aliases})이 실제로 담겨 있는가? "
    "참조 사진과 같은 대상인지 건축 형태·색·배치를 비교하라. 사진 속에 현판·안내판·비석 등 글자가 있으면 "
    "보이는 대로 옮겨 적어라(한자·한글 그대로, 없으면 빈 문자열).\n"
    "각도·계절·조명이 달라도 같은 대상이면 일치다. 확신이 없으면 confidence를 낮게 줘라.\n"
    '설명 없이 아래 JSON 한 개만 출력: {{"match": true|false, "confidence": 0.0~1.0, '
    '"text_seen": "<읽은 글자>", "reason": "<한 문장>"}}'
)

_JSON_RE = re.compile(r"\{.*\}", re.S)


def _parse(raw: str) -> dict | None:
    m = _JSON_RE.search(raw or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(d, dict) or "match" not in d:
        return None
    try:
        conf = float(d.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    return {
        "match": bool(d.get("match")),
        "confidence": max(0.0, min(1.0, conf)),
        "text_seen": str(d.get("text_seen") or "").strip(),
        "reason": str(d.get("reason") or "").strip(),
    }


def _norm(s: str) -> str:
    return re.sub(r"[\s\-·ㆍ()\[\]「」『』'\"“”‘’,.]", "", s or "").lower()


def text_matches(text_seen: str, needles: list[str]) -> bool:
    """읽은 글자에 타깃/장소/별칭(한자 포함)의 핵심 토큰이 들어 있나. 두 글자 이상만 인정한다."""
    t = _norm(text_seen)
    if len(t) < 2:
        return False
    for n in needles:
        for tok in re.split(r"[\s/,]+", n or ""):
            k = _norm(tok)
            if len(k) >= 2 and k in t:
                return True
    return False


def npc_line(*, verified: bool | None, target: str, text_seen: str) -> str:
    """판정을 도깨비 말로. 검증이 화면에서 '도깨비가 알아봤다'로 보이게 한다."""
    if verified is True:
        if text_seen:
            return f"허허, '{text_seen}' 글자가 선명하구나. {target}을(를) 잘 담았느니라."
        return f"옳다, {target}이(가) 틀림없구나. 기억석이 반응하는 것을 느끼느냐."
    if verified is False:
        return f"으음… 이것은 {target}이 아닌 듯하구나. 주변을 다시 살펴 그것을 담아 오거라."
    # unverified — 판정 불가. 플레이어를 막지 않고 신뢰로 넘긴다(행위 완료).
    return "허허, 내 눈이 잠시 흐려졌구나. 네가 담아 온 것을 믿어 보겠느니라."


async def verify_photo(
    *,
    image_data_url: str,
    target: str,
    place_name: str,
    ref_images: list[str],
    aliases: list[str] | None = None,
) -> dict:
    """사진 1장 판정. 어떤 실패에도 raise 하지 않는다 — mode로 구분해 돌려준다.

    반환: {verified: bool|None, mode: "vision"|"unverified", confidence, text_seen, reason, npc_line, refs_used}
    """
    s = get_settings()
    aliases = [a for a in (aliases or []) if a]
    refs = [r for r in ref_images if r][: s.photo_verify_max_refs]
    needles = [target, place_name, *aliases]
    t0 = time.perf_counter()

    if not image_data_url:
        logger.warning("사진 검증: 이미지 없음 (target=%s)", target)
        return _result(None, "unverified", 0.0, "", "이미지 없음", target, len(refs))

    prompt = _PROMPT.format(
        place=place_name or "이 장소", target=target or "목표물",
        aliases=", ".join(aliases) if aliases else "없음", n_ref=len(refs),
    )
    try:
        raw = await get_vision_llm().generate_with_images(prompt, [image_data_url, *refs])
    except Exception as e:
        # 모델 장애 = 판정 불가. 플레이는 계속돼야 하므로 unverified로 내려보내고 원인만 남긴다.
        logger.warning("사진 검증 모델 실패(target=%s, %.1fs) → unverified: %s",
                       target, time.perf_counter() - t0, e)
        return _result(None, "unverified", 0.0, "", f"모델 호출 실패: {type(e).__name__}", target, len(refs))

    parsed = _parse(raw)
    if parsed is None:
        logger.warning("사진 검증 응답 파싱 실패(target=%s): %s", target, (raw or "")[:120].replace("\n", " "))
        return _result(None, "unverified", 0.0, "", "응답 형식 오류", target, len(refs))

    by_text = text_matches(parsed["text_seen"], needles)
    verified = bool(parsed["match"] and (parsed["confidence"] >= s.photo_verify_confidence or by_text))
    logger.info(
        "사진 검증: %s → %s (match=%s conf=%.2f 글자=%s%s, 참조 %d장, %.1fs)",
        target, "통과" if verified else "불일치", parsed["match"], parsed["confidence"],
        repr(parsed["text_seen"]) if parsed["text_seen"] else "없음", " ✓일치" if by_text else "",
        len(refs), time.perf_counter() - t0,
    )
    return _result(verified, "vision", parsed["confidence"], parsed["text_seen"], parsed["reason"], target, len(refs))


def _result(verified, mode, confidence, text_seen, reason, target, refs_used) -> dict:
    return {
        "verified": verified,
        "mode": mode,
        "confidence": confidence,
        "text_seen": text_seen,
        "reason": reason,
        "npc_line": npc_line(verified=verified, target=target, text_seen=text_seen),
        "refs_used": refs_used,
    }
