# ============================================================
# [v1] 시나리오 응답 계약 테스트 — 생성 결과가 응답에서 유실되지 않는지 (이슈 #40)
# pipeline: AI 백엔드 / 서빙 레이어 (테스트, 네트워크 0 — generate_scenario를 스텁)
# 구현(요약): generate_scenario가 채운 키가 ScenarioGenResponse 미선언으로 잘려나가지
#            않는지 검증. 과거 wishlist_content_ids·transport가 조용히 사라졌다.
# 구현일: 2026-08-02 | 작성: kys (branch-parity/kys/v1)
# ============================================================
from fastapi.testclient import TestClient

from app.main import create_app

# generate_scenario가 실제로 채워 반환하는 형태(네트워크·LLM 없이 고정)
_FAKE_SCENARIO = {
    "scenario_id": "scn_종로_test",
    "title": "종로의 기억석 — 1조각 코스",
    "region": "종로",
    "type": "custom",
    "node_sequence": [],
    "stone_total": 1,
    "anchor_node_id": "tour_1",
    "is_public": False,
    "created_by": "tester",
    "budget": 30000,
    "transport": "car",
    "wishlist_content_ids": ["264337", "264338"],
    "is_branching": False,
    "route_tree": None,
}

_REQUEST = {
    "user_id": "tester",
    "start": {"lat": 37.5796, "lng": 126.9770},
    "transport": "car",
    "budget": 30000,
    "wishlist": [{"content_id": "264337"}, {"content_id": "264338"}],
}


def _client(monkeypatch) -> TestClient:
    """generate_scenario를 고정 반환으로 갈아끼운 클라이언트(결정론·오프라인)."""
    import app.api.routes as routes

    async def _fake(_req):
        return dict(_FAKE_SCENARIO)

    monkeypatch.setattr(routes, "generate_scenario", _fake)
    return TestClient(create_app())


def test_response_keeps_wishlist_and_transport(monkeypatch):
    """[회귀 #40] 위시 앵커·이동수단이 응답에서 잘려나가지 않는다."""
    res = _client(monkeypatch).post("/v1/scenarios", json=_REQUEST)
    assert res.status_code == 200
    body = res.json()
    assert body["wishlist_content_ids"] == ["264337", "264338"]
    assert body["transport"] == "car"


def test_response_preserves_every_generated_key(monkeypatch):
    """생성기가 채운 키는 하나도 응답에서 사라지지 않는다(스키마 미선언 유실 방지)."""
    res = _client(monkeypatch).post("/v1/scenarios", json=_REQUEST)
    dropped = set(_FAKE_SCENARIO) - set(res.json())
    assert not dropped, f"응답 스키마 미선언으로 유실된 키: {sorted(dropped)}"
