# ============================================================
# [v1] 테스트 스위트 공통 격리 — 주변 .env가 오프라인 테스트를 바꾸지 못하게 한다
# pipeline: AI 백엔드 / 테스트 인프라
# 구현(요약): 결함보고 20260904 #4 조치로 .env에 DOKKAEBI_SCENARIO_FOOD_PER_ROUTE=2가
#            켜졌다. 그러자 식음 후보를 주입하지 않는 기존 오프라인 테스트들이
#            interleave_food를 통해 **실 TourAPI를 호출**하기 시작했다(스위트 15초 → 87초,
#            네트워크가 없으면 결과가 흔들린다). 각 테스트 파일 헤더가 "네트워크 0"을
#            표방하므로, 스위치 기본값을 여기서 끄고 필요한 테스트만 스스로 켜게 한다.
#
#            ⚠️ 식음 삽입 자체를 검증하는 테스트는 monkeypatch로 값을 올려 쓴다 —
#               이 fixture보다 뒤에 적용되므로 그대로 이긴다.
#               (tests/test_food.py::test_switch_on_reads_settings,
#                tests/test_llm_integration_defects.py 결함#4 묶음)
# 구현일: 2026-09-06 | 작성: pjh (agent-qa/pjh/v1)
# ============================================================
import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def _offline_food_switch(monkeypatch):
    """식음 삽입 스위치를 기본 OFF로 고정한다(네트워크 유발 지점 차단)."""
    monkeypatch.setattr(get_settings(), "scenario_food_per_route", 0)
