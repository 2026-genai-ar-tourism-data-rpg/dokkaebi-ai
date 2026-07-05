# ============================================================
# [v3] food.py 단위테스트 — 구글 priceLevel 밴드 방식 (네트워크 0, 전부 결정론)
# 골든 케이스 = 시나리오_MVP_예시 §0: 안국역 · 예산 20,000원 · (인원수 변수화)
# 구현일: 2026-07-04 | 작성: pjh (food-budget/pjh/v1)
# 실행: pytest tests/test_food.py  (env 스위치 미설정 상태 기준)
# ============================================================
import pytest

from app.tourapi.food import (
    band_match_score, budget_to_band, gap_segments, interleave_food,
    pick_candidate, plan_slots,
)

# ---- 골든 route: MVP 예시 코스의 관광지 축 (운현궁 → 인사동 → 광화문=피날레) ----
ROUTE = [
    {"node_id": "tour_unhyeon", "name": "운현궁", "map_y": 37.5745, "map_x": 126.9856},
    {"node_id": "tour_insa",    "name": "인사동", "map_y": 37.5717, "map_x": 126.9857},
    {"node_id": "tour_gwang",   "name": "광화문", "map_y": 37.5759, "map_x": 126.9769,
     "is_finale_hint": True},
]

# ---- 주입용 후보 (구글 priceLevel 밴드가 부착된 형태를 흉내) ----
CANDS = [
    {"node_id": "food_cafe_ikseon", "name": "익선동 한옥카페", "kind": "cafe",
     "price_band": 2, "price_band_label": "₩₩", "price_source": "google",
     "map_y": 37.5742, "map_x": 126.9904},
    {"node_id": "food_tea_insa", "name": "인사동 전통찻집", "kind": "cafe",
     "price_band": 1, "price_band_label": "₩", "price_source": "google",
     "map_y": 37.5740, "map_x": 126.9856},
    {"node_id": "food_gukbap", "name": "종로 국밥집", "kind": "food",
     "price_band": 1, "price_band_label": "₩", "price_source": "google",
     "map_y": 37.5703, "map_x": 126.9880},
    {"node_id": "food_pasta", "name": "익선동 파스타", "kind": "food",
     "price_band": 2, "price_band_label": "₩₩", "price_source": "google",
     "map_y": 37.5744, "map_x": 126.9900},
    {"node_id": "food_hanjeongsik", "name": "인사동 한정식", "kind": "food",
     "price_band": 3, "price_band_label": "₩₩₩", "price_source": "google",
     "map_y": 37.5720, "map_x": 126.9860},
    {"node_id": "food_unknown", "name": "가격미상 식당", "kind": "food",
     "price_band": None, "price_band_label": "가격대 정보 없음", "price_source": None,
     "map_y": 37.5721, "map_x": 126.9861},
]


# ============ 1. 예산 → 목표 밴드 (경계는 config 정책값) ============
def test_budget_to_band_boundaries():
    assert budget_to_band(8_000) == 1      # < 1만 = ₩
    assert budget_to_band(20_000) == 2     # 1만~3만 = ₩₩
    assert budget_to_band(45_000) == 3     # 3만~6만 = ₩₩₩
    assert budget_to_band(120_000) == 4    # 6만+ = ₩₩₩₩

def test_headcount_lowers_target_band():
    """같은 총예산 → 인원 많을수록 1인 예산이 줄어 목표 밴드 하락 (인원수=곱 계수)."""
    assert budget_to_band(60_000 / 1) == 4
    assert budget_to_band(60_000 / 3) == 2
    assert budget_to_band(60_000 / 8) == 1


# ============ 2. 밴드 매칭 — 일치 최우선, 초과 하드컷, 과소 감점, 미상 중간 ============
def test_band_match_exact_beats_cheaper():
    assert band_match_score(2, target_band=2) == 0          # 딱 맞는 급 = 최고점
    assert band_match_score(1, target_band=2) == 1          # 한 밴드 아래 = 감점(허용)
    assert band_match_score(3, target_band=2) is None       # 초과 = 하드컷

def test_unknown_band_between_one_and_two_below():
    unknown = band_match_score(None, target_band=3)
    assert band_match_score(2, 3) < unknown < band_match_score(1, 3)

def test_pick_candidate_prefers_exact_band():
    """목표 ₩₩일 때: 파스타(₩₩)가 국밥(₩)·한정식(₩₩₩)·미상보다 우선."""
    chosen = pick_candidate(CANDS, "food", target_band=2, exclude_ids=set())
    assert chosen["node_id"] == "food_pasta"

def test_pick_candidate_hard_cuts_over_budget_band():
    """목표 ₩일 때: 한정식(₩₩₩)·파스타(₩₩)는 절대 안 뽑히고 국밥(₩)."""
    chosen = pick_candidate(CANDS, "food", target_band=1, exclude_ids=set())
    assert chosen["node_id"] == "food_gukbap"


# ============ 3. 슬롯 구성 — 다운그레이드/폴백 (정책 임계) ============
def test_plan_slots_composition_and_downgrade():
    assert plan_slots(20000, 1, per_route=2) == ["food", "cafe"]
    assert plan_slots(20000, 6, per_route=2) == ["cafe"]     # 1인 3,333원 → 식사 불가
    assert plan_slots(20000, 10, per_route=2) == []          # 1인 2,000원 → 전부 폴백
    assert plan_slots(None, 1, per_route=2) == ["food", "cafe"]
    assert plan_slots(20000, 1, per_route=0) == []


# ============ 4. 삽입 위치 — 최장 구간, 피날레 뒤 금지 (v1 유지) ============
def test_gap_segments_sorted_and_never_after_finale():
    segs = gap_segments(ROUTE)
    assert segs[0][0] >= segs[-1][0]
    assert all(1 <= idx <= len(ROUTE) - 1 for _, idx, _, _ in segs)


# ============ 5. 골든 케이스 — interleave_food 최종 route ============
def test_golden_anguk_20000_solo():
    """MVP 예시: 2만원·혼자 → 목표 ₩₩ → 파스타(₩₩)+한옥카페(₩₩) 삽입, 피날레 유지."""
    out = interleave_food(ROUTE, budget=20000, headcount=1, per_route=2, candidates=CANDS)
    food_nodes = [n for n in out if n.get("kind") in ("food", "cafe")]
    assert {n["node_id"] for n in food_nodes} == {"food_pasta", "food_cafe_ikseon"}
    assert out[0]["node_id"] == "tour_unhyeon"               # 시작 유지
    assert out[-1]["node_id"] == "tour_gwang"                # 피날레 맨 뒤 유지 ⚠️핵심
    assert all("fragment_id" not in n for n in food_nodes)   # 기억석 필드 미부여
    assert all(n["price_band"] <= 2 for n in food_nodes)     # 목표 밴드 초과 없음

def test_golden_same_budget_more_people_downgrades():
    """같은 2만원인데 6명 → 1인 3,333원 → 카페(₩)만, 식사 노드 없음."""
    out = interleave_food(ROUTE, budget=20000, headcount=6, per_route=2, candidates=CANDS)
    food_nodes = [n for n in out if n.get("kind") in ("food", "cafe")]
    assert food_nodes and all(n["kind"] == "cafe" for n in food_nodes)
    assert all(n["price_band"] <= 1 for n in food_nodes)     # 목표 ₩ 초과 금지

def test_big_budget_prefers_higher_band():
    """예산 15만·2인 → 1인 7.5만 → 목표 ₩₩₩₩, 상한 내 최고 밴드(한정식 ₩₩₩) 선택."""
    out = interleave_food(ROUTE, budget=150000, headcount=2, per_route=1, candidates=CANDS)
    food_nodes = [n for n in out if n.get("kind") == "food"]
    assert food_nodes[0]["node_id"] == "food_hanjeongsik"

def test_budget_too_small_falls_back_to_zero():
    out = interleave_food(ROUTE, budget=2000, headcount=4, per_route=2, candidates=CANDS)
    assert out == ROUTE                                      # 삽입 0, 경로 그대로(실패 아님)

def test_switch_off_preserves_behavior():
    """settings 기본(per_route=0) → 완전 no-op = 기존 동작 100% 보존 (seam 계약)."""
    assert interleave_food(ROUTE, budget=20000) == ROUTE

def test_no_invented_krw_estimates():
    """원 단위 추정(spend_est) 재유입 금지 — 밴드 방식 회귀 방지."""
    out = interleave_food(ROUTE, budget=20000, headcount=1, per_route=2, candidates=CANDS)
    assert all("spend_est" not in n for n in out)