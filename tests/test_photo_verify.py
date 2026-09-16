# ============================================================
# [v1] 사진 검증 테스트 — 판정 규칙·글자 대조·장애 폴백·엔드포인트 계약
# 구현일: 2026-09-16 | 작성: kys (photo-verify/kys/v1)
# ============================================================
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.exceptions import LLMCallError
from app.llm.base import LLMProvider
from app.llm.client import LLMClient
from app.services import photo_verify_service as svc

IMG = "data:image/jpeg;base64,/9j/AAAA"


class _Stub(LLMProvider):
    """비전 모델 응답을 정해 주는 스텁. 받은 이미지 수도 기록한다."""
    def __init__(self, raw): self.raw, self.images = raw, None
    async def generate(self, prompt, **kw): return self.raw
    async def generate_with_images(self, prompt, images, **kw):
        self.images = images
        if isinstance(self.raw, Exception):
            raise self.raw
        return self.raw


def _use(monkeypatch, raw):
    stub = _Stub(raw)
    monkeypatch.setattr(svc, "get_vision_llm", lambda: LLMClient(provider=stub))
    return stub


class TestTextMatch:
    def test_hanja_and_korean_tokens(self):
        assert svc.text_matches("興化門", ["흥화문", "興化門"])
        assert svc.text_matches("경희궁 흥화문 안내", ["흥화문"])
        assert not svc.text_matches("", ["흥화문"])
        assert not svc.text_matches("문", ["흥화문"])            # 한 글자 우연 일치는 안 본다
        assert not svc.text_matches("근정전", ["흥화문", "경희궁"])


@pytest.mark.asyncio
class TestVerify:
    async def test_match_with_high_confidence(self, monkeypatch):
        stub = _use(monkeypatch, '{"match": true, "confidence": 0.92, "text_seen": "", "reason": "같은 문"}')
        out = await svc.verify_photo(image_data_url=IMG, target="흥화문", place_name="경희궁",
                                     ref_images=["https://r/1.jpg", "https://r/2.jpg", "https://r/3.jpg"], aliases=["興化門"])
        assert out["verified"] is True and out["mode"] == "vision"
        assert "틀림없구나" in out["npc_line"]
        # 참조 사진 상한(기본 2) — 플레이어 사진 1 + 참조 2 = 3장만 보냈다
        assert stub.images[0] == IMG and len(stub.images) == 1 + get_settings().photo_verify_max_refs
        assert out["refs_used"] == get_settings().photo_verify_max_refs

    async def test_low_confidence_rescued_by_text(self, monkeypatch):
        _use(monkeypatch, '{"match": true, "confidence": 0.4, "text_seen": "興化門", "reason": "현판"}')
        out = await svc.verify_photo(image_data_url=IMG, target="흥화문", place_name="경희궁",
                                     ref_images=[], aliases=["興化門"])
        assert out["verified"] is True
        assert "興化門" in out["npc_line"] and "선명" in out["npc_line"]   # 일치한 낱말이 대사로

    async def test_low_confidence_without_text_fails(self, monkeypatch):
        _use(monkeypatch, '{"match": true, "confidence": 0.4, "text_seen": "", "reason": "비슷"}')
        out = await svc.verify_photo(image_data_url=IMG, target="흥화문", place_name="경희궁", ref_images=[])
        assert out["verified"] is False and out["mode"] == "vision"

    async def test_no_match(self, monkeypatch):
        _use(monkeypatch, '{"match": false, "confidence": 0.95, "text_seen": "CITI", "reason": "빌딩"}')
        out = await svc.verify_photo(image_data_url=IMG, target="흥화문", place_name="경희궁", ref_images=[])
        assert out["verified"] is False and "아닌 듯" in out["npc_line"]

    async def test_model_failure_is_unverified_not_error(self, monkeypatch):
        _use(monkeypatch, LLMCallError("upstream down"))
        out = await svc.verify_photo(image_data_url=IMG, target="흥화문", place_name="경희궁", ref_images=[])
        assert out["verified"] is None and out["mode"] == "unverified"
        assert "믿어" in out["npc_line"]                          # 플레이어를 막지 않는다

    async def test_garbage_output_is_unverified(self, monkeypatch):
        _use(monkeypatch, "허허 잘 모르겠구나")
        out = await svc.verify_photo(image_data_url=IMG, target="흥화문", place_name="경희궁", ref_images=[])
        assert out["verified"] is None and out["reason"] == "응답 형식 오류"

    async def test_json_embedded_in_prose_is_parsed(self, monkeypatch):
        _use(monkeypatch, '판정 결과입니다:\n{"match": true, "confidence": "0.88", "text_seen": "숭정전", "reason": "x"}\n끝')
        out = await svc.verify_photo(image_data_url=IMG, target="숭정전", place_name="경희궁", ref_images=[])
        assert out["verified"] is True and out["confidence"] == 0.88

    async def test_missing_image(self, monkeypatch):
        stub = _use(monkeypatch, '{"match": true, "confidence": 1}')
        out = await svc.verify_photo(image_data_url="", target="x", place_name="y", ref_images=[])
        assert out["mode"] == "unverified" and stub.images is None   # 모델을 부르지도 않는다


@pytest.mark.asyncio
class TestOcrPath:
    """provider가 match=null(OCR)로 답할 때 — 글자 대조가 판정을 끝낸다."""

    async def test_reversed_hanja_from_signboard_passes(self, monkeypatch):
        # 실측: 흥화문 정면 사진을 OCR이 "門化興 / ㅎ 한국관광공사"로 읽었다.
        _use(monkeypatch, '{"match": null, "confidence": 0.98, "text_seen": "門化興 ㅎ 한국관광공사", "reason": "OCR 글자 대조"}')
        out = await svc.verify_photo(image_data_url=IMG, target="흥화문", place_name="경희궁", ref_images=[], aliases=["興化門"])
        assert out["verified"] is True and out["mode"] == "ocr"
        assert "門化興" in out["npc_line"] and "한국관광공사" not in out["npc_line"]   # 워터마크 글자는 인용 안 함

    async def test_info_board_korean_passes_and_line_quotes_only_the_match(self, monkeypatch):
        long_text = "경희궁 흥화문 경희궁지 이곳은 조선 시대의 6대 궁궐 가운데 하나인 " * 6
        _use(monkeypatch, '{"match": null, "confidence": 0.9, "text_seen": "%s", "reason": "OCR"}' % long_text)
        out = await svc.verify_photo(image_data_url=IMG, target="흥화문", place_name="경희궁", ref_images=[])
        assert out["verified"] is True
        # 실측 결함 재현: 안내판 전문이 말풍선에 통째로 들어갔다 → 일치한 낱말만 인용한다
        assert "'흥화문'" in out["npc_line"] and len(out["npc_line"]) < 60
        assert out["text_seen"].startswith("경희궁 흥화문")            # 원문은 응답 필드에 남긴다(도감 캡션용)

    async def test_no_text_is_unverified_trust(self, monkeypatch):
        # 글자 없는 사진(마당·전경) — OCR로는 판정 불가 → 막지 않고 신뢰로 넘긴다.
        _use(monkeypatch, '{"match": null, "confidence": 0.0, "text_seen": "", "reason": "OCR"}')
        out = await svc.verify_photo(image_data_url=IMG, target="마당", place_name="경희궁", ref_images=[])
        assert out["verified"] is None and out["mode"] == "unverified"

    async def test_other_text_is_mismatch(self, monkeypatch):
        _use(monkeypatch, '{"match": null, "confidence": 0.95, "text_seen": "CITI 은행", "reason": "OCR"}')
        out = await svc.verify_photo(image_data_url=IMG, target="흥화문", place_name="경희궁", ref_images=[])
        assert out["verified"] is False


class TestUpstageOcrProvider:
    def test_data_url_decoding_and_url_rejected(self):
        from app.llm.providers.upstage_ocr import _decode_data_url
        data, mime = _decode_data_url("data:image/png;base64,aGVsbG8=")
        assert data == b"hello" and mime == "image/png"
        data, mime = _decode_data_url("aGVsbG8=")
        assert data == b"hello" and mime == "image/jpeg"
        with pytest.raises(LLMCallError):
            _decode_data_url("https://tong.visitkorea.or.kr/x.jpg")

    @pytest.mark.asyncio
    async def test_response_mapped_to_contract(self, monkeypatch):
        import httpx
        from app.llm.providers import upstage_ocr as mod

        class _Resp:
            status_code = 200
            text = ""
            def json(self): return {"text": "門化興\n한국관광공사", "confidence": 0.97, "pages": []}

        class _Client:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, headers=None, files=None, data=None):
                assert url.endswith("/document-digitization") and data == {"model": "ocr"}
                assert "document" in files
                return _Resp()

        monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
        p = mod.UpstageOcrProvider(base_url="https://api.upstage.ai/v1", api_key="k")
        import json
        out = json.loads(await p.generate_with_images("무시", ["data:image/jpeg;base64,aGVsbG8="]))
        assert out["match"] is None and out["text_seen"] == "門化興 한국관광공사" and out["confidence"] == 0.97


class TestEndpoint:
    def test_contract_with_mock_vision(self, monkeypatch):
        from app.llm import client as llm_client
        from app.llm.providers.mock import MockProvider
        monkeypatch.setattr(svc, "get_vision_llm", lambda: LLMClient(provider=MockProvider()))
        from app.main import create_app
        c = TestClient(create_app())
        r = c.post("/v1/photo/verify", json={
            "user_id": "guest_x", "node_id": "tour_1604784", "node_name": "경희궁 흥화문",
            "target": "흥화문", "ref_images": ["https://r/1.jpg"], "aliases": ["興化門"],
            "image_b64": "/9j/AAAA",                             # 순수 base64 → 서버가 data URI로 감싼다
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["mode"] == "vision" and body["verified"] is True
        assert set(body) >= {"verified", "mode", "confidence", "text_seen", "reason", "npc_line", "refs_used"}
        assert r.headers.get("X-Request-Id")

    def test_missing_required_fields_is_422(self):
        from app.main import create_app
        c = TestClient(create_app())
        assert c.post("/v1/photo/verify", json={"node_id": "x"}).status_code == 422
