# ============================================================
# [v1] 회귀: /v1/search가 좌표·반경을 받는다 (조치계획 20260912 QA1 선택안)
# pipeline: AI 백엔드 / 서빙 레이어 (테스트, 네트워크 0 — search_keyword를 스텁)
# 구현(요약): 앱이 '탐색 반경 → 가고싶은 곳' 순서로 바뀌는데 검색이 키워드 전용이라
#            반경을 먼저 골라도 전국 아무 곳이나 잡혔다. lat·lng → dist_m·거리순,
#            radius_m → 반경 밖 제외를 검증하고, 좌표 미전송 시 기존 동작(정확도 순서
#            보존·dist_m None)이 그대로인지도 함께 본다.
# 구현일: 2026-09-12 | 작성: pjh (wish-dupe-search-radius/pjh/v1)
# ============================================================
from fastapi.testclient import TestClient

from app.main import create_app

# 종로(출발점 가정) 기준 — 가까운 곳부터 먼 곳까지. 검색 API는 관련도 순으로 준다고 가정.
_START = {"lat": 37.5703, "lng": 126.9856}
_CANDS = [
    {"tour_content_id": "300", "name": "부산 태종대", "addr": "부산 영도구",
     "map_y": 35.0536, "map_x": 129.0857},              # 약 325km
    {"tour_content_id": "100", "name": "보신각터", "addr": "서울 종로구",
     "map_y": 37.5698, "map_x": 126.9837},              # 약 180m
    {"tour_content_id": "200", "name": "종묘", "addr": "서울 종로구",
     "map_y": 37.5710, "map_x": 126.9951},              # 약 840m
]


def _client(monkeypatch) -> TestClient:
    """TourAPI 검색을 고정 후보로 갈아끼운 클라이언트(결정론·오프라인)."""
    import app.api.routes as routes

    async def _fake(keyword, content_type_id=12, top_n=8):
        return [dict(c) for c in _CANDS]

    monkeypatch.setattr(routes._tour, "search_keyword", _fake)
    return TestClient(create_app())


def test_좌표를_주면_거리를_채워_거리순으로_준다(monkeypatch):
    res = _client(monkeypatch).get("/v1/search", params={"keyword": "종", **_START})

    assert res.status_code == 200
    cands = res.json()["candidates"]
    assert [c["content_id"] for c in cands] == ["100", "200", "300"]
    assert cands[0]["dist_m"] < cands[1]["dist_m"] < cands[2]["dist_m"]


def test_반경을_주면_반경_밖은_빠진다(monkeypatch):
    res = _client(monkeypatch).get(
        "/v1/search", params={"keyword": "종", **_START, "radius_m": 1000},
    )

    cands = res.json()["candidates"]
    assert [c["content_id"] for c in cands] == ["100", "200"]   # 부산(325km) 제외
    assert all(c["dist_m"] <= 1000 for c in cands)


def test_반경_안에_아무것도_없으면_빈_결과다(monkeypatch):
    """앱이 '반경 밖이라 안 나온다'를 그대로 보여줄 수 있어야 한다(0건 = 정상 응답)."""
    res = _client(monkeypatch).get(
        "/v1/search", params={"keyword": "태종대", **_START, "radius_m": 100},
    )

    assert res.status_code == 200
    assert res.json()["candidates"] == []


def test_좌표를_안_주면_기존_동작_그대로다(monkeypatch):
    """하위호환 — 정렬을 건드리지 않고 dist_m은 None으로 나간다."""
    res = _client(monkeypatch).get("/v1/search", params={"keyword": "종"})

    cands = res.json()["candidates"]
    assert [c["content_id"] for c in cands] == ["300", "100", "200"]
    assert all(c["dist_m"] is None for c in cands)
