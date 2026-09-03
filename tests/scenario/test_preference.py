# ============================================================
# [v1] 테스트: 탐험 입력 → 생성 파라미터 변환 (preference.py)
# pipeline: AI 백엔드 / 시나리오 (앱 마법사 입력이 생성에 실제로 먹히는지)
# 구현(요약): 앱 3단계 입력이 계약에만 있고 생성엔 안 쓰이던 회귀를 막는다 —
#            duration→노드 수·반경, difficulty→트리거 반경·힌트 수, companion→인원수,
#            tags→후보 우선순위, region="auto"→주소 기반 시군구 판정.
#            모르는 값/미전송이 기본값으로 떨어지는지(하위호환)도 함께 본다.
# 구현일: 2026-08-18 | 작성: kys (explore-input-wiring/kys/v1)
# ============================================================
from app.scenario.preference import (
    apply_hint_limit,
    headcount_for,
    hint_limit_for,
    infer_region,
    node_count_for,
    radius_for,
    rank_by_tags,
    trigger_radius_for,
)


def test_duration_이_노드수와_반경을_늘린다():
    assert node_count_for("2h", 5) == 4
    assert node_count_for("half", 5) == 6
    assert node_count_for("full", 5) == 8
    assert radius_for("2h", 2000) == 2000
    assert radius_for("half", 2000) == 3000
    assert radius_for("full", 2000) == 4000


def test_모르는_값은_기본값으로_떨어진다():
    """미전송·오타·구버전 앱 → 예외가 아니라 기존 동작."""
    assert node_count_for(None, 5) == 5
    assert node_count_for("일주일", 5) == 5
    assert radius_for(None, 2000) == 2000
    assert trigger_radius_for(None) == 100
    assert hint_limit_for("몰라") == 2
    assert headcount_for(None) == 1


def test_difficulty_가_트리거반경과_힌트수를_정한다():
    assert trigger_radius_for("easy") == 150
    assert trigger_radius_for("normal") == 100
    assert trigger_radius_for("hard") == 60
    assert hint_limit_for("easy") == 3
    assert hint_limit_for("hard") == 1


def test_힌트는_난이도만큼만_남는다():
    mission = {"type": "PHOTO_FIND", "order": "찾아라", "hints": ["h1", "h2", "h3"]}
    assert apply_hint_limit(mission, "hard")["hints"] == ["h1"]
    assert apply_hint_limit(mission, "normal")["hints"] == ["h1", "h2"]
    assert apply_hint_limit(mission, "easy")["hints"] == ["h1", "h2", "h3"]
    # 원본은 안 건드린다(생성 결과 재사용 지점이 있어서)
    assert mission["hints"] == ["h1", "h2", "h3"]
    assert apply_hint_limit(None, "easy") is None


def test_companion_이_인원수가_된다():
    assert headcount_for("solo") == 1
    assert headcount_for("friend") == 2
    assert headcount_for("couple") == 2
    assert headcount_for("family") == 4
    # 앱이 인원수를 직접 보냈으면 그 값이 이긴다
    assert headcount_for("solo", 6) == 6


def test_취향_태그가_맞는_후보를_앞으로_당긴다():
    nodes = [
        {"node_id": "a", "name": "역삼 카페거리", "dist_m": 100},
        {"node_id": "b", "name": "경복궁", "dist_m": 900},
        {"node_id": "c", "name": "이름없는 골목", "dist_m": 300},
    ]
    ranked = rank_by_tags(nodes, ["#고궁"])
    assert ranked[0]["node_id"] == "b", "고궁 태그인데 900m 경복궁이 안 올라왔다"
    # 태그가 없으면 원래 순서 그대로(거리순 특성 보존)
    assert rank_by_tags(nodes, []) == nodes
    assert rank_by_tags(nodes, None) == nodes


def test_태그는_후보를_제외하지_않는다():
    """태그로 거르면 후보가 말라 코스가 깨진다 — 순서만 바꾼다."""
    nodes = [{"node_id": str(i), "name": f"장소{i}", "dist_m": i * 10} for i in range(5)]
    assert len(rank_by_tags(nodes, ["#고궁"])) == 5


def test_region_auto_는_후보_주소에서_시군구를_뽑는다():
    nodes = [
        {"addr1": "서울특별시 종로구 삼일대로 464"},
        {"addr1": "서울특별시 종로구 인사동길 12"},
        {"addr1": "서울특별시 중구 명동길 1"},
    ]
    assert infer_region(nodes, fallback="이 지역") == "종로구"
    # 구가 없는 지방은 시/군 단위
    assert infer_region([{"addr1": "경상북도 안동시 도산면"}], "이 지역") == "안동시"
    # 주소가 없으면 폴백
    assert infer_region([{"name": "이름만"}], "이 지역") == "이 지역"
    assert infer_region([], "이 지역") == "이 지역"
