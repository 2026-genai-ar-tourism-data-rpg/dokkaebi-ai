# ============================================================
# [v1] 비인기 라벨링 — density_tier (TourAPI BigData 기반)
# pipeline: AI 백엔드 / 시나리오 (노드 메타: 인기/비인기)
# 구현(요약): LocgoHubTar(중심성)+TatsCnctrRate(집중률) 기반으로 비인기 앵커를 선택.
#            기본은 지역 벌크 조회 + TTL 캐시, 개별 tAtsNm 조회는 제한 fallback으로만 사용.
# 구현일: 2026-06-19 | 작성: kys (node-content/kys/v1)
# 관련: 기획 1-3 적재 우선순위(비인기 라벨링은 별도 워크스트림)
# ============================================================
# [v2] 비인기 라벨링 + 비인기 앵커 선택 — TourAPI BigData 실수치
# pipeline: AI 백엔드 / 시나리오 (build_route ① 단계 hook — 비인기 샛길)
# 구현(요약): mock 해시 라벨 제거. LocgoHubTar(중심성)+TatsCnctrRate(집중률) 기반으로
#            비인기 앵커 k개를 선택해 route에 강제 포함. 기본은 지역 벌크 조회 + TTL 캐시,
#            개별 tAtsNm 조회는 제한 fallback으로만 사용. 실데이터 없으면 선택 안 함(빈 리스트).
# 구현일: 2026-07-04 | 작성: ljs (lowtraffic-select/ljs/v1)
# 관련: 기획 10(관광 분산)·11-2(앵커+샛길), WEEKLY-PLAN '이지선 — ① 비인기 앵커 선택'
# ============================================================
from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

from app.config import get_settings
from app.core.logger import get_logger
from app.tourapi.bigdata import fetch_concentration_by_name_sync, fetch_density_snapshot_sync

logger = get_logger(__name__)

_VALID_DENSITY_TIERS = {"popular", "low_traffic"}


def density_label(node: dict) -> str:
    """'popular' | 'low_traffic'.

    select_lowtraffic_anchors에서 이미 선택된 node는 density_tier="low_traffic"가 붙어 있으므로
    generator.py 후속 호출에서 덮어쓰지 않고 그대로 유지한다.
    """
    tier = node.get("density_tier")
    if tier in _VALID_DENSITY_TIERS:
        return tier
    return "popular"


def reward_weight(tier: str) -> float:
    """비인기지 보상 가중치(분산 유도). 실수치는 EDA로 확정."""
    return 1.5 if tier == "low_traffic" else 1.0


def select_lowtraffic_anchors(nodes: list[dict], k: int) -> list[dict]:
    """비인기 노드 중 k개를 경로 앵커(샛길)로 선택. build_route ① 단계 hook.

    정책:
      - 기본: 종로 BigData 벌크 snapshot에서 로컬 이름 매칭
      - fallback: 벌크 매칭 실패 node만 최대 config.density_targeted_fallback_limit개 개별 tAtsNm 조회
      - 실데이터 없으면 선택하지 않음(return [])
    """
    if k <= 0 or not nodes:
        return []

    s = get_settings()
    snapshot = fetch_density_snapshot_sync(s.density_default_region)
    if not snapshot:
        return []

    concentration_rows = snapshot.get("concentration_rows") or []
    hub_rows = snapshot.get("hub_rows") or []
    if not concentration_rows or not hub_rows:
        return []

    area_cd = snapshot.get("areaCd")
    signgu_cd = snapshot.get("signguCd")
    if not area_cd or not signgu_cd:
        return []

    concentration_index = _build_concentration_index(concentration_rows)
    hub_candidates = _filter_hub_rows(hub_rows, s.density_allowed_hub_category)

    selected_candidates: list[dict[str, Any]] = []
    fallback_used = 0

    for node in nodes[:s.density_candidate_limit]:
        if not node.get("node_id"):
            continue

        name = node.get("name") or ""
        if not name:
            continue

        matched_rows = _match_concentration_rows(name, concentration_index)
        if matched_rows is None and fallback_used < s.density_targeted_fallback_limit:
            fallback_used += 1
            matched_rows = fetch_concentration_by_name_sync(area_cd, signgu_cd, name)

        if not matched_rows:
            continue

        avg_rate = _avg_cnctr_rate(matched_rows)
        if avg_rate is None:
            continue

        hub_row = _match_hub_row(node, hub_candidates)
        hub_rank = _parse_int(hub_row.get("hubRank")) if hub_row else None
        if hub_rank is not None and hub_rank <= s.density_hub_popular_top_n:
            continue

        selected_candidates.append({
            "node": node,
            "avg_rate": avg_rate,
            "hub_rank": hub_rank,
            "dist_m": _parse_float(node.get("dist_m"), default=math.inf),
        })

    if not selected_candidates:
        return []

    selected_candidates.sort(
        key=lambda item: (
            item["avg_rate"],
            -(item["hub_rank"] or 0),
            item["dist_m"],
        )
    )
    selected = [item["node"] for item in selected_candidates[:k]]
    for node in selected:
        node["density_tier"] = "low_traffic"
    return selected


def _build_concentration_index(rows: list[dict]) -> dict[str, list[dict]]:
    """tAtsNm 정규화 이름 → 원본 concentration row 리스트."""
    index: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = _normalize_name(row.get("tAtsNm"))
        if key:
            index[key].append(row)
    return dict(index)


def _match_concentration_rows(name: str, index: dict[str, list[dict]]) -> list[dict] | None:
    """node name과 concentration tAtsNm을 매칭한다.

    concentration row에는 좌표가 없으므로 이름 exact → 포함 관계 순서로만 판단한다.
    """
    target = _normalize_name(name)
    if not target:
        return None
    if target in index:
        return index[target]

    matches = [
        (abs(len(key) - len(target)), -len(key), key)
        for key in index
        if target in key or key in target
    ]
    if not matches:
        return None

    _, _, best_key = sorted(matches)[0]
    return index[best_key]


def _filter_hub_rows(rows: list[dict], category: str | None) -> list[dict]:
    """중심 관광지 row 중 관광지 카테고리만 사용한다."""
    if not category:
        return rows
    return [row for row in rows if row.get("hubCtgryLclsNm") == category]


def _match_hub_row(node: dict, rows: list[dict]) -> dict | None:
    """node name과 hubTatsNm을 매칭한다. 후보가 여러 개면 좌표가 가장 가까운 row를 선택."""
    target = _normalize_name(node.get("name"))
    if not target:
        return None

    exact = [row for row in rows if _normalize_name(row.get("hubTatsNm")) == target]
    candidates = exact or [
        row for row in rows
        if _contains_match(target, _normalize_name(row.get("hubTatsNm")))
    ]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    node_x = _parse_float(node.get("map_x"))
    node_y = _parse_float(node.get("map_y"))
    if node_x is None or node_y is None:
        return sorted(candidates, key=lambda row: _rank_sort_value(row.get("hubRank")))[0]

    return sorted(
        candidates,
        key=lambda row: (
            _haversine_m(node_x, node_y, _parse_float(row.get("mapX")), _parse_float(row.get("mapY"))),
            _rank_sort_value(row.get("hubRank")),
        ),
    )[0]


def _contains_match(a: str, b: str) -> bool:
    return bool(a and b and (a in b or b in a))


def _normalize_name(value: Any) -> str:
    """장소명 비교 전용 정규화. 원본 API key/value는 변경하지 않는다."""
    text = str(value or "").strip()
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"[\s·ㆍ/\\\-_.,]+", "", text)
    return text.lower()


def _avg_cnctr_rate(rows: list[dict]) -> float | None:
    rates: list[float] = []
    for row in rows:
        rate = _parse_float(row.get("cnctrRate"))
        if rate is not None:
            rates.append(rate)
    if not rates:
        return None
    return sum(rates) / len(rates)


def _parse_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _rank_sort_value(value: Any) -> int:
    rank = _parse_int(value)
    return rank if rank is not None else 999999


def _haversine_m(x1: float | None, y1: float | None, x2: float | None, y2: float | None) -> float:
    """경도/위도 두 점 사이 거리(m). 좌표가 없으면 무한대."""
    if x1 is None or y1 is None or x2 is None or y2 is None:
        return math.inf

    radius_m = 6371000.0
    lat1 = math.radians(y1)
    lat2 = math.radians(y2)
    dlat = math.radians(y2 - y1)
    dlng = math.radians(x2 - x1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * radius_m * math.asin(math.sqrt(a))
