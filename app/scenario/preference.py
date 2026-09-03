# ============================================================
# [v1] 탐험 입력 → 생성 파라미터 변환 — duration·companion·difficulty·tags·region
# pipeline: AI 백엔드 / 시나리오 (앱 「나만의 코스 만들기」 입력을 생성 로직에 반영)
# 구현(요약): 앱 마법사 3단계 입력이 계약에만 있고 생성에는 안 쓰이던 것을 실제 파라미터로
#            번역한다 — duration→노드 수·반경 배율, difficulty→트리거 반경·힌트 노출 수,
#            companion→인원수(식음 예산 게이팅), tags→후보 선호 가중(거리순 재정렬).
#            region="auto"(또는 빈 값)면 후보 주소(addr1)에서 시군구를 뽑아 라벨을 정한다
#            — 앱은 GPS 좌표만 알고 행정구역명을 모르기 때문(역지오코딩 미도입).
#            모르는 값·미전송은 전부 기본값으로 떨어진다 → 기존 동작 그대로(하위호환).
# 구현일: 2026-08-18 | 작성: kys (explore-input-wiring/kys/v1)
# ============================================================
from collections import Counter

from app.core.logger import get_logger

logger = get_logger(__name__)

# --- duration: 앱 「시간」 선택 → 방문 장소 수 · 반경 배율 ---
# 2시간이면 멀리 못 간다. 하루면 더 많이·더 넓게. 반경은 transport 기본값에 곱한다.
_DURATION_COUNT = {"2h": 4, "half": 6, "full": 8}
_DURATION_RADIUS_SCALE = {"2h": 1.0, "half": 1.5, "full": 2.0}

# --- difficulty: 앱 「난이도」 선택 → GPS 트리거 반경 · 힌트 노출 수 ---
# 쉬움일수록 반경을 넓게(도착 인증이 쉬움) 힌트를 많이. 어려움은 그 반대.
# TODO(임시): 실기기 개발 중 이동 없이 도착 인증 테스트하려고 전부 10km로 임시 확대.
#             테스트 끝나면 원래 값({"easy": 150, "normal": 100, "hard": 60})으로 되돌릴 것.
_DIFFICULTY_TRIGGER_M = {"easy": 10000, "normal": 10000, "hard": 10000}
_DIFFICULTY_HINTS = {"easy": 3, "normal": 2, "hard": 1}

# --- companion: 앱 「동행」 선택 → 인원수(1인 예산 = budget/headcount) ---
_COMPANION_HEADCOUNT = {"solo": 1, "friend": 2, "couple": 2, "family": 4}

# --- tags: 앱 「추천 취향」 → 후보 이름·주소·개요에서 찾을 키워드 ---
# 취향에 맞는 후보를 '가깝게' 취급해 거리순 선택에서 먼저 뽑히게 한다(제외가 아니라 가중).
_TAG_KEYWORDS = {
    "고궁": ("궁", "궁궐", "종묘", "행궁", "대궐"),
    "역사": ("역사", "유적", "사적", "문화재", "고분", "성곽", "기념관", "박물관", "능"),
    "한옥": ("한옥", "고택", "서원", "향교", "민속마을", "전통가옥"),
    "전통문화": ("전통", "민속", "공예", "문화원", "서예", "한복", "국악", "장인"),
    "카페": ("카페", "커피", "로스터", "디저트", "찻집"),
    "맛집": ("맛집", "식당", "음식", "시장", "먹거리"),
    "한적한 곳": ("공원", "산책", "숲", "정원", "둘레길", "호수", "쉼터", "자연"),
    "사진 명소": ("전망", "야경", "포토", "명소", "조망", "타워", "전망대"),
}
# 태그 1개 일치당 빼줄 가상 거리(m). 거리순 선택이 dist_m를 보므로 '더 가까운 것'처럼 만든다.
# 도보 기본 반경(2km) 기준으로 정했다 — 취향에 맞으면 1.5km 더 멀어도 먼저 뽑힌다.
# 취향을 골랐는데 코앞의 무관한 장소로 코스가 채워지면 고른 의미가 없다.
_TAG_BONUS_M = 1500.0

_DEFAULT_DURATION = "2h"
_DEFAULT_DIFFICULTY = "normal"
_DEFAULT_COMPANION = "solo"


def node_count_for(duration: str | None, default: int) -> int:
    """탐험 시간 → 방문 장소(기억석 조각) 수. 모르는 값이면 설정 기본값."""
    return _DURATION_COUNT.get(_norm(duration), default)


def radius_for(duration: str | None, base_radius_m: int) -> int:
    """탐험 시간 → 후보 검색 반경. transport로 정해진 기본 반경에 배율을 곱한다."""
    return int(base_radius_m * _DURATION_RADIUS_SCALE.get(_norm(duration), 1.0))


def headcount_for(companion: str | None, headcount: int = 1) -> int:
    """동행 → 인원수. 앱이 headcount를 직접 보냈으면(>1) 그 값을 존중한다."""
    if headcount and headcount > 1:
        return headcount
    return _COMPANION_HEADCOUNT.get(_norm(companion), 1)


def trigger_radius_for(difficulty: str | None) -> int:
    """난이도 → GPS 도착 인증 반경(m). 노드 상세 반경이 붙으면 그쪽이 우선."""
    return _DIFFICULTY_TRIGGER_M.get(_norm(difficulty), _DIFFICULTY_TRIGGER_M[_DEFAULT_DIFFICULTY])


def hint_limit_for(difficulty: str | None) -> int:
    """난이도 → 노드당 노출할 힌트 개수. 어려움은 1개만 준다."""
    return _DIFFICULTY_HINTS.get(_norm(difficulty), _DIFFICULTY_HINTS[_DEFAULT_DIFFICULTY])


def rank_by_tags(nodes: list[dict], tags: list[str] | None) -> list[dict]:
    """취향 태그에 맞는 후보를 앞으로 당긴다(제외하지 않음 — 후보가 마르면 코스가 깨진다).

    dist_m에서 태그 일치당 _TAG_BONUS_M을 빼 '가상 거리'로 재정렬한다. 실제 dist_m은
    건드리지 않는다(앱이 표시하고 build_route가 동선 계산에 쓰는 값이라서).
    """
    keys = _tag_keys(tags)
    if not keys or not nodes:
        return nodes
    ranked = sorted(nodes, key=lambda n: _virtual_dist(n, keys))
    hits = sum(1 for n in nodes if _tag_hits(n, keys))
    logger.info("취향 태그 %s → 후보 %d개 중 %d개 우선 배치", list(keys), len(nodes), hits)
    return ranked


def apply_hint_limit(mission: dict | None, difficulty: str | None) -> dict | None:
    """미션 힌트를 난이도만큼만 남긴다. 힌트가 없으면 그대로."""
    if not mission:
        return mission
    hints = mission.get("hints") or []
    if not hints:
        return mission
    return {**mission, "hints": list(hints)[: hint_limit_for(difficulty)]}


def infer_region(nodes: list[dict], fallback: str) -> str:
    """후보 주소에서 지역 라벨(시군구)을 유추. 못 찾으면 fallback.

    앱은 GPS 좌표만 알고 행정구역명을 모른다 — region을 앱이 고정으로 보내던 탓에
    어디서 만들어도 제목·조각 id가 '종로'로 나왔다. 후보들의 addr1 최빈 시군구를 쓴다.
    """
    names = [_gu_of(n.get("addr1") or n.get("addr") or "") for n in nodes]
    names = [n for n in names if n]
    if not names:
        return fallback
    top, _cnt = Counter(names).most_common(1)[0]
    return top


def _gu_of(addr: str) -> str | None:
    """'서울특별시 종로구 삼일대로 464' → '종로구'. 구가 없으면 시/군 단위."""
    for token in addr.split():
        if token.endswith("구") and len(token) > 1:
            return token
    for token in addr.split()[1:]:            # 첫 토큰(시·도)은 건너뛴다
        if token.endswith(("시", "군")) and len(token) > 1:
            return token
    return None


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _tag_keys(tags: list[str] | None) -> set[str]:
    """앱이 보낸 태그 라벨('#고궁'·'고궁')을 알고 있는 키로 정규화."""
    keys = set()
    for t in tags or []:
        label = (t or "").strip().lstrip("#")
        if label in _TAG_KEYWORDS:
            keys.add(label)
    return keys


def _tag_hits(node: dict, keys: set[str]) -> int:
    """노드의 이름·주소·개요에 취향 키워드가 몇 번 걸리는지(태그 단위로 셈)."""
    haystack = " ".join(
        str(node.get(f) or "") for f in ("name", "addr1", "addr2", "addr", "overview", "cat")
    )
    return sum(1 for k in keys if any(w in haystack for w in _TAG_KEYWORDS[k]))


def _virtual_dist(node: dict, keys: set[str]) -> float:
    """정렬용 가상 거리 — 좌표·거리 결측 후보는 뒤로 민다(기존 거리순 특성 유지)."""
    dist = node.get("dist_m")
    base = float(dist) if dist is not None else 10_000_000.0
    return base - _TAG_BONUS_M * _tag_hits(node, keys)
