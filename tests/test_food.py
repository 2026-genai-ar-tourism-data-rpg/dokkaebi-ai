# ============================================================
# [v4] food.py 단위테스트 — 구글 priceLevel 밴드 방식 (네트워크 0, 전부 결정론)
# 골든 케이스 = 시나리오_MVP_예시 §0: 안국역 · 예산 20,000원 · (인원수 변수화)
#
# v4 변경 (2026-07-11, 커버리지 실측 40% 대응):
#   · 미상(price_band=None) = 하드컷 — "가격 모르는 가게 추천" 금지 정책 확정
#     (v3까지는 미상=1.5점 통과 → 저예산에서 유효 후보가 전부 잘리고 미상만
#      살아남아 뽑히는 역설 발생. 실측: 예산 8,000원 → 뉘조(미상) 삽입)
#   · §6 경계 케이스 테스트 추가 (예산 0/과다, 후보 0, 전부 미상, 다운그레이드)
# 구현일: 2026-07-04 | v4: 2026-07-11 | 작성: pjh (food-realdata/pjh/v1)
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

# ---- [v4] 밴드가 전부 미상인 후보 풀 (실측: 종로 후보의 60%가 이 상태) ----
CANDS_ALL_UNKNOWN = [
    {"node_id": "food_u1", "name": "미상식당A", "kind": "food",
     "price_band": None, "price_band_label": "가격대 정보 없음", "price_source": None,
     "map_y": 37.5721, "map_x": 126.9861},
    {"node_id": "food_u2", "name": "미상카페B", "kind": "cafe",
     "price_band": None, "price_band_label": "가격대 정보 없음", "price_source": None,
     "map_y": 37.5741, "map_x": 126.9855},
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


# ============ 2. 밴드 매칭 — 일치 최우선, 초과 하드컷, 과소 감점, 미상 하드컷 ============
def test_band_match_exact_beats_cheaper():
    assert band_match_score(2, target_band=2) == 0          # 딱 맞는 급 = 최고점
    assert band_match_score(1, target_band=2) == 1          # 한 밴드 아래 = 감점(허용)
    assert band_match_score(3, target_band=2) is None       # 초과 = 하드컷

def test_unknown_band_is_hard_cut():
    """[정책 v4, 2026-07-11] 밴드 미상 = 하드컷.
    커버리지 실측 40%(종로): 낮은 목표 밴드에선 유효 후보가 전부 잘리고
    미상만 살아남아 '가격 모르는 가게'가 뽑히는 역설 발생 → 미상 배제로 확정.
    (되돌리려면 config food_unknown_band_score에 숫자 지정 — env 무코드 튜닝)"""
    assert band_match_score(None, target_band=1) is None
    assert band_match_score(None, target_band=4) is None

def test_pick_candidate_prefers_exact_band():
    """목표 ₩₩일 때: 파스타(₩₩)가 국밥(₩)·한정식(₩₩₩)·미상보다 우선."""
    chosen = pick_candidate(CANDS, "food", target_band=2, exclude_ids=set())
    assert chosen["node_id"] == "food_pasta"

def test_pick_candidate_hard_cuts_over_budget_band():
    """목표 ₩일 때: 한정식(₩₩₩)·파스타(₩₩)는 절대 안 뽑히고 국밥(₩)."""
    chosen = pick_candidate(CANDS, "food", target_band=1, exclude_ids=set())
    assert chosen["node_id"] == "food_gukbap"

def test_unknown_never_beats_known_lower_band():
    """미상 vs 밴드 아는 하위 후보 → 항상 밴드 아는 쪽 (미상은 후보 자격 자체가 없음)."""
    chosen = pick_candidate(CANDS, "food", target_band=3, exclude_ids=set())
    assert chosen["node_id"] != "food_unknown"


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


# ============ 6. [v4] 경계 케이스 — 커버리지 실측 40% 대응 (2026-07-11) ============
def test_all_unknown_candidates_insert_nothing():
    """핵심 회귀: 미상 후보만 있으면 삽입 0 — '가격 모르는 가게 추천' 금지.
    (v3 실측: 예산 8,000원 → 유효 후보 전멸 → 뉘조(미상) 삽입되던 동작의 재발 방지)"""
    out = interleave_food(ROUTE, budget=8000, headcount=1, per_route=2,
                          candidates=CANDS_ALL_UNKNOWN)
    assert out == ROUTE                                      # 경로는 그대로, 실패 아님

def test_budget_zero_inserts_nothing_route_intact():
    """예산 0 → 카페 최소 임계(2,500) 미달 → 슬롯 성립 불가 → 삽입 0, 경로 정상."""
    out = interleave_food(ROUTE, budget=0, headcount=1, per_route=2, candidates=CANDS)
    assert out == ROUTE

def test_budget_huge_no_hard_cut_targets_top_band():
    """예산 과다(100만) → 목표 ₩₩₩₩ → 어떤 유효 밴드도 하드컷 없음, 미상은 여전히 배제."""
    assert budget_to_band(1_000_000) == 4
    out = interleave_food(ROUTE, budget=1_000_000, headcount=1, per_route=2,
                          candidates=CANDS)
    food_nodes = [n for n in out if n.get("kind") in ("food", "cafe")]
    assert food_nodes                                        # 삽입은 됨
    assert all(n["price_band"] is not None for n in food_nodes)   # 미상 배제 유지

def test_empty_candidates_no_crash():
    """후보 0개 → 삽입 0, 크래시 없음, 경로 정상."""
    out = interleave_food(ROUTE, budget=20000, headcount=1, per_route=2, candidates=[])
    assert out == ROUTE

def test_downgrade_path_also_hard_cuts_unknown():
    """식사 후보가 미상뿐 → 카페 다운그레이드 경로에서도 미상 하드컷 유지.
    밴드 아는 저가카페(₩)만 뽑히고 미상은 어느 슬롯에도 못 들어감."""
    mixed = CANDS_ALL_UNKNOWN + [
        {"node_id": "food_cheap_cafe", "name": "저가카페", "kind": "cafe",
         "price_band": 1, "price_band_label": "₩", "price_source": "google",
         "map_y": 37.5740, "map_x": 126.9856},
    ]
    out = interleave_food(ROUTE, budget=8000, headcount=1, per_route=2, candidates=mixed)
    food_nodes = [n for n in out if n.get("kind") in ("food", "cafe")]
    assert all(n["price_band"] is not None for n in food_nodes)
    assert all(n["node_id"] not in ("food_u1", "food_u2") for n in food_nodes)