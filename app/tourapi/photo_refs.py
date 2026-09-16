# ============================================================
# [v1] 사진 참조 접근층 — 장소별 "찍을 것"과 그 참조 사진을 TourAPI에서 꺼낸다
# pipeline: AI 백엔드 / 외부 데이터 (PHOTO_FIND·PATH_TRACE 미션이 소비)
# 구현(요약): "외부 소스 1개 = 파일 1개" 컨벤션(bigdata.py·google_places.py와 동일).
#   · 왜: photo_targets를 LLM이 "대문", "건물 외관"처럼 지어냈다. 장소마다 실제로
#     무엇이 있는지는 TourAPI가 이미 안다 — 관광사진 갤러리(PhotoGalleryService1)는
#     사진마다 세부 태그(흥화문·숭정전·경회루…)가 붙어 있고 detailImage2엔 노드 사진이
#     4~16장 있다. 지어내지 말고 꺼내 쓴다.
#   · 두 종류의 참조 사진을 구분해 내보낸다:
#       targets[].ref_image — 그 세부 명소가 찍힌 사진. 비전 모델의 "같은 대상인가" 비교용
#       ar_reference_images — 노드 사진 전부(상한). ARKit Augmented Images 후보.
#         평면(안내판)인지 골라내지 않는다 — 어느 사진이 평면인지는 ARKit이 등록 시
#         품질 경고로 알려주고, 비평면은 그냥 인식이 안 될 뿐 해를 끼치지 않는다.
#   · 실패해도 시나리오 생성을 절대 막지 않음 — 빈 구조 반환 + 경고 로그.
#   · 캐시: 장소 사진은 거의 안 바뀜 → tourapi_cache_ttl_s(7일). 갤러리 검색·상세 이미지
#     둘 다 캐싱해서 재생성 시 TourAPI 호출 0.
#   · 출처: 공사 사진은 공공누리 — photographer를 credit으로 같이 실어 앱이 표기한다.
# 구현일: 2026-09-16 | 작성: kys (photo-refs/kys/v1)
# ============================================================
import json
import re

from app.config import get_settings
from app.core.cache import get_cache
from app.core.logger import get_logger
from app.tourapi.base import request

logger = get_logger(__name__)

_GALLERY_OP = "gallerySearchList1"
_DETAIL_IMAGE_OP = "detailImage2"

# 세부 명소가 아닌 태그 — 장소명·행정구역·유형·계절·시간대. 타깃 후보에서 뺀다.
# (갤러리 태그 실측: "경희궁, 서울특별시 종로구, 사적 제271호, 고궁, 궁궐, 6월 버킷, 6월")
_GENERIC_TAGS = {
    "국가유산", "문화유산", "유형문화유산", "사적", "고궁", "궁궐", "한옥", "서울", "야경",
    "봄", "여름", "가을", "겨울", "봄꽃", "단풍", "설경", "일출", "일몰", "노을",
    "추천여행", "버킷", "여행", "관광", "명소", "축제", "행사", "야간개장",
    # 건축 일반명사·풍경 — 그 장소만의 것이 아니다 (실측: 운현궁 → "기와집"이 타깃으로 나왔다)
    "기와집", "기와지붕", "지붕", "담장", "나무", "하늘", "구름", "풍경", "전경", "산책",
    "데이트", "포토존", "인생샷", "사진", "야외",
}
_GENERIC_PATTERNS = (
    re.compile(r"^(사적|보물|국보)\s*제?\s*\d+호$"),
    re.compile(r"^\d{1,2}월(\s*\S+)?$"),          # "6월", "6월 버킷", "6월 추천여행"
    re.compile(r"(특별시|광역시|도|시|군|구)$"),    # 행정구역
    re.compile(r"(야경|봄|여름|가을|겨울)$"),         # "경복궁 야경", "경희궁 봄"
    # 촬영단·공모 태그 (실측: 경복궁 → "사진기자단"(27장) "프레임코리아1기"(18장)가 1·3위였고,
    #  운현궁 → "2025 대한민국 관광공모전(사진)"이 타깃으로 나왔다)
    re.compile(r"(기자단|프레임코리아|서포터즈|\d+기)$"),
    re.compile(r"(공모전|사진전|\(사진\)|페스티벌)"),
    re.compile(r"^(19|20)\d{2}\s"),                 # "2025 대한민국 …" 연도로 시작하는 행사 태그
)
# 장소명 앞에 붙는 도시 접두 — "서울 운현궁"의 토큰 분해 때 "서울"을 장소 토큰으로 안 본다.
_CITY_PREFIX = re.compile(r"^(서울|부산|대구|인천|광주|대전|울산|세종|경주|전주|수원)\s+")


def _place_tokens(place_name: str) -> set[str]:
    """'경희궁 흥화문' → {'경희궁 흥화문', '경희궁', '흥화문'} — 이 이름의 조각은 타깃이 아니다."""
    base = _CITY_PREFIX.sub("", place_name.strip())
    toks = {place_name.strip(), base}
    toks.update(t for t in base.split() if len(t) >= 2)
    return toks


def _is_generic(tag: str, place_name: str, photo_title: str = "") -> bool:
    t = tag.strip()
    if not t or t in _place_tokens(place_name):
        return True
    # 사진의 galTitle은 '이 사진이 속한 장소'다 — 세부 명소일 수 없다. 제목이 그 태그로
    # 시작하면("경복궁 겨울" ↔ "경복궁") 같은 뜻으로 본다.
    # (실측: 건청궁 검색에 걸린 '경복궁 겨울' 사진 때문에 '경복궁'이 건청궁의 타깃으로 나왔다)
    title = (photo_title or "").strip()
    if title and (t == title or title.startswith(t + " ") or title.startswith(t)) and len(t) >= 2:
        return True
    if t in _GENERIC_TAGS:
        return True
    return any(p.search(t) for p in _GENERIC_PATTERNS)


def _strip_place(tag: str, place_name: str, photo_title: str) -> str:
    """'경복궁 향원정' → '향원정'. 장소명이 접두로 붙은 태그를 세부 명소 이름으로 정리한다."""
    for prefix in sorted({*_place_tokens(place_name), photo_title.strip()}, key=len, reverse=True):
        if prefix and tag.startswith(prefix + " ") and len(tag) > len(prefix) + 1:
            return tag[len(prefix) + 1:].strip()
    return tag


def _tags(raw: str | None) -> list[str]:
    return [t.strip() for t in (raw or "").split(",") if t.strip()]


async def _cached_items(cache_key: str, base_url: str, op: str, params: dict) -> list[dict]:
    """TourAPI 호출을 캐시로 감싼다. 실패는 호출부가 처리한다(여기서 삼키지 않음)."""
    cache = get_cache()
    hit = await cache.get(cache_key)
    if hit is not None:
        return json.loads(hit)
    items = (await request(base_url, op, params))["items"]
    await cache.set(cache_key, json.dumps(items, ensure_ascii=False), get_settings().tourapi_cache_ttl_s)
    return items


async def gallery_photos(keyword: str, rows: int = 60) -> list[dict]:
    """관광사진 갤러리에서 키워드로 사진 목록. [{url, title, tags[], photographer}]."""
    s = get_settings()
    items = await _cached_items(
        f"gallery:{keyword}:{rows}",
        f"{s.tourapi_data_base_url.rstrip('/')}/PhotoGalleryService1",
        _GALLERY_OP,
        {"keyword": keyword, "numOfRows": rows, "arrange": "A"},
    )
    out = []
    for it in items:
        url = it.get("galWebImageUrl")
        if not url:
            continue
        out.append({
            "url": url,
            "title": it.get("galTitle") or "",
            "tags": _tags(it.get("galSearchKeyword")),
            "photographer": it.get("galPhotographer") or "한국관광공사",
        })
    return out


async def detail_images(content_id: str, rows: int = 20) -> list[dict]:
    """노드(contentId)의 소개 이미지 목록. [{url, name}]."""
    s = get_settings()
    items = await _cached_items(
        f"tourimages:{content_id}",
        s.tourapi_base_url,
        _DETAIL_IMAGE_OP,
        {"contentId": content_id, "imageYN": "Y", "numOfRows": rows},
    )
    return [
        {"url": it["originimgurl"], "name": it.get("imgname") or ""}
        for it in items if it.get("originimgurl")
    ]


def _why_from_overview(target: str, overview: str, max_len: int = 70) -> str | None:
    """overview에서 그 타깃을 언급한 문장 하나 — "왜 이걸 봐야 하는지".
    예: 흥화문 → "현판 글씨가 명필이라 밤에도 빛이나 … '야주개'"."""
    if not overview or not target:
        return None
    head = target.split()[0][:3]                      # "흥화문 현판" → "흥화"
    hits = [x.strip() for x in re.split(r"(?<=[.。!?])\s+", " ".join(overview.split())) if head in x]
    if not hits:
        return None
    # 첫 문장은 대개 "X은 Y의 정문이다" 같은 정의문이다(실측). 볼 이유를 주는 건 그 뒤의
    # 이야기 — 현판·전설·유래. 그런 낱말이 든 문장을 먼저, 없으면 가장 긴 문장을 고른다.
    story = re.compile(r"(현판|글씨|명필|전설|유래|이름|불리|특징|유명|아름|섬세|화려|최초|유일|보물|국보)")
    ranked = sorted(hits, key=lambda x: (bool(story.search(x)), len(x)), reverse=True)
    sent = ranked[0]
    return sent if len(sent) <= max_len else sent[:max_len].rstrip() + "…"


def select_targets(photos: list[dict], place_name: str, overview: str, *, max_targets: int) -> list[dict]:
    """갤러리 사진의 세부 태그에서 '찍을 것'을 고른다. 순수 함수(테스트용).

    점수 = 그 태그가 붙은 사진 수 + (overview에 언급되면 큰 가중) — 언급된 건 그 장소의
    이야기가 있는 것이라 우선한다. 각 타깃엔 그 태그가 붙은 첫 사진을 참조로 단다.
    """
    score: dict[str, int] = {}
    best_photo: dict[str, dict] = {}
    focus: dict[str, int] = {}          # 그 사진에 붙은 '세부' 태그 수 — 적을수록 그 대상에 집중된 사진
    photo_set: dict[str, frozenset] = {}  # 태그별 '붙은 사진 집합' — 동의어 태그 접기용
    for p in photos:
        title = p.get("title") or ""
        specific = [
            _strip_place(t, place_name, title)
            for t in p["tags"] if not _is_generic(t, place_name, title)
        ]
        specific = [t for t in specific if t and not _is_generic(t, place_name, title)]
        for t in specific:
            score[t] = score.get(t, 0) + 1
            photo_set[t] = photo_set.get(t, frozenset()) | {p["url"]}
            # 태그 하나만 단 사진이 여러 태그를 단 사진보다 그 대상을 잘 보여준다.
            if t not in best_photo or len(specific) < focus[t]:
                best_photo[t] = p
                focus[t] = len(specific)
    if not score:
        return []
    flat_overview = " ".join((overview or "").split())
    ranked = sorted(
        score.items(),
        key=lambda kv: (kv[1] + (5 if kv[0].split()[0][:3] in flat_overview else 0), kv[1]),
        reverse=True,
    )
    # 같은 사진들에만 함께 붙는 태그는 같은 대상의 다른 이름이다 — 하나만 남긴다.
    # (실측: 세종마을 음식문화거리 → "먹자골목·먹자거리·이색거리"가 사진 4장을 그대로 공유해 3타깃으로 나왔다)
    seen_sets: set[frozenset] = set()
    deduped = []
    for tag, n in ranked:
        ps = photo_set[tag]
        if ps in seen_sets:
            continue
        seen_sets.add(ps)
        deduped.append((tag, n))
    targets = []
    for tag, n in deduped[:max_targets]:
        p = best_photo[tag]
        why = _why_from_overview(tag, overview)
        targets.append({
            "name": tag,
            "why": why,
            "ref_image": p["url"],
            "credit": p["photographer"],
            "photo_count": n,
        })
    return targets


async def build_photo_refs(name: str, content_id: str | None, overview: str) -> dict:
    """장소 하나의 사진 참조 묶음. 어떤 실패에도 raise 하지 않는다.

    반환: {"targets": [...], "ar_reference_images": [url, ...], "source": "gallery|detail|none"}
    """
    s = get_settings()
    empty = {"targets": [], "ar_reference_images": [], "source": "none"}
    if not s.tourapi_service_key or not name:
        return empty

    photos: list[dict] = []
    try:
        photos = await gallery_photos(name)
    except Exception as e:                           # 부가정보 — 실패=없는 셈, 경로는 계속
        logger.warning("갤러리 조회 실패(%s) → 타깃 없이 진행: %s", name, e)

    targets = select_targets(photos, name, overview, max_targets=s.photo_refs_max_targets)

    ar_images: list[str] = []
    source = "none"
    if content_id:
        try:
            ar_images = [d["url"] for d in await detail_images(content_id)][: s.photo_refs_max_images]
            if ar_images:
                source = "detail"
        except Exception as e:
            logger.warning("노드 이미지 조회 실패(%s/%s): %s", name, content_id, e)
    if not ar_images and photos:
        # 자기 사진이 없는 노드(궁 안의 세부 건물 등) — 갤러리 사진으로라도 채운다.
        ar_images = [p["url"] for p in photos][: s.photo_refs_max_images]
        source = "gallery"

    logger.info(
        "사진 참조: %s → 타깃 %d개%s · AR 참조 %d장(%s)",
        name, len(targets),
        f"[{', '.join(t['name'] for t in targets)}]" if targets else "",
        len(ar_images), source,
    )
    if not targets and not ar_images:
        # 사진이 아예 없는 장소 — PHOTO_FIND 검증이 텍스트 기반으로 떨어진다는 뜻. 남겨둔다.
        logger.warning("사진 참조 없음: %s(%s) — 촬영 미션이 검증 없이(행위 완료) 돌아간다", name, content_id)
    return {"targets": targets, "ar_reference_images": ar_images, "source": source}


async def attach_photo_refs(mission: dict, node: dict) -> dict:
    """PHOTO_FIND·PATH_TRACE 미션에 사진 참조를 붙인다. 다른 타입은 그대로 돌려준다.

    타깃이 하나라도 나오면 photo_targets(문자열 계약)를 실존 명소 이름으로 바꾼다 —
    앱·node_schema는 여전히 문자열 배열을 읽으므로 깨지지 않는다. LLM이 쓴 값은
    llm_photo_targets 에 보존해 무엇이 대체됐는지 로그·응답에서 볼 수 있게 한다.
    """
    if not isinstance(mission, dict) or mission.get("type") not in ("PHOTO_FIND", "PATH_TRACE"):
        return mission
    refs = await build_photo_refs(
        node.get("name") or "", node.get("tour_content_id"), node.get("overview") or "",
    )
    mission["photo_refs"] = refs["targets"]
    mission["ar_reference_images"] = refs["ar_reference_images"]
    if refs["targets"]:
        llm_targets = list(mission.get("photo_targets") or [])
        mission["llm_photo_targets"] = llm_targets
        mission["photo_targets"] = [t["name"] for t in refs["targets"]]
        logger.info(
            "photo_targets 대체: %s → %s (node=%s)",
            llm_targets, mission["photo_targets"], node.get("node_id"),
        )
    return mission
