# ============================================================
# [v1] photo_refs 테스트 — 갤러리 태그 → 타깃 선정, 참조 사진 폴백, 실패 격리
# 구현일: 2026-09-16 | 작성: kys (photo-refs/kys/v1)
# ============================================================
import pytest

from app.config import get_settings
from app.tourapi import photo_refs as pr

OVERVIEW = (
    "흥화문은 경희궁의 정문이다. 경희궁 근처 얕은 고개를 '야주개'라 하였는데, "
    "이는 흥화문의 현판 글씨가 명필이라 밤에도 빛이나 그 광채가 고개까지 훤하게 비추었다 하여 붙여진 이름이다. "
    "숭정전은 경희궁의 정전이다."
)

def _photo(url, tags, who="한국관광공사 이범수"):
    return {"url": url, "title": "경희궁", "tags": tags, "photographer": who}

GALLERY = [
    _photo("https://x/1.jpg", ["경희궁", "서울특별시 종로구", "사적 제271호", "고궁", "궁궐", "자정문", "6월 버킷", "6월"]),
    _photo("https://x/2.jpg", ["경희궁", "서울특별시 종로구", "고궁", "궁궐", "숭정문"]),
    _photo("https://x/3.jpg", ["경희궁", "서울특별시 종로구", "고궁", "궁궐", "숭정문"]),
    _photo("https://x/4.jpg", ["경희궁", "서울특별시 종로구", "고궁", "궁궐", "숭정전", "유형문화유산"]),
    _photo("https://x/5.jpg", ["경희궁", "서울특별시 종로구", "사적 제271호", "고궁", "궁궐", "흥화문"]),
    _photo("https://x/6.jpg", ["경희궁", "서울특별시 종로구", "고궁", "궁궐"]),          # 세부 태그 없음
    _photo("https://x/7.jpg", ["경희궁", "봄", "야경", "경희궁 야경"]),                # 전부 제네릭
]


class TestSelectTargets:
    def test_generic_tags_are_excluded(self):
        targets = pr.select_targets(GALLERY, "경희궁", "", max_targets=10)
        names = {t["name"] for t in targets}
        assert names == {"자정문", "숭정문", "숭정전", "흥화문"}
        for bad in ("경희궁", "서울특별시 종로구", "사적 제271호", "고궁", "궁궐", "6월", "6월 버킷", "봄", "야경", "유형문화유산"):
            assert bad not in names

    def test_overview_mention_beats_photo_count(self):
        # 숭정문은 사진 2장으로 최다지만, overview는 흥화문·숭정전을 말한다 → 그 둘이 먼저.
        targets = pr.select_targets(GALLERY, "경희궁", OVERVIEW, max_targets=2)
        assert [t["name"] for t in targets] == ["흥화문", "숭정전"] or \
               [t["name"] for t in targets] == ["숭정전", "흥화문"]

    def test_target_carries_ref_image_credit_and_why(self):
        targets = pr.select_targets(GALLERY, "경희궁", OVERVIEW, max_targets=4)
        hwa = next(t for t in targets if t["name"] == "흥화문")
        assert hwa["ref_image"] == "https://x/5.jpg"
        assert hwa["credit"] == "한국관광공사 이범수"
        assert "명필" in hwa["why"]                  # overview에서 그 문장을 뽑아왔다
        assert len(hwa["why"]) <= 71
        # 언급이 없는 타깃은 why가 None — 지어내지 않는다
        ja = next(t for t in targets if t["name"] == "자정문")
        assert ja["why"] is None

    def test_place_tokens_title_and_crew_tags_excluded_and_prefix_stripped(self):
        # 실측 결함 재현: 노드명 조각·사진 소속지·촬영단 태그가 타깃으로 나왔고, 장소명 접두가 남았다.
        photos = [
            {"url": "u1", "title": "경희궁", "tags": ["경희궁", "흥화문"], "photographer": "a"},
            {"url": "u2", "title": "경복궁", "tags": ["경복궁", "사진기자단", "프레임코리아1기"], "photographer": "b"},
            {"url": "u3", "title": "경복궁", "tags": ["경복궁", "경복궁 향원정"], "photographer": "c"},
            {"url": "u4", "title": "운현궁", "tags": ["운현궁", "노안당", "기와집"], "photographer": "d"},
        ]
        names = [t["name"] for t in pr.select_targets(photos, "경희궁 흥화문", "", max_targets=10)]
        assert "경희궁" not in names and "경복궁" not in names          # 노드명 조각·소속지
        assert "사진기자단" not in names and "프레임코리아1기" not in names
        assert "기와집" not in names
        assert "향원정" in names and "경복궁 향원정" not in names        # 접두 제거
        assert "흥화문" not in names                                    # '경희궁 흥화문'의 토큰

    def test_title_prefix_and_contest_tags_excluded(self):
        # 실측 결함 재현 2차: 제목 '경복궁 겨울'의 '경복궁', '2025 대한민국 관광공모전(사진)'
        photos = [
            {"url": "u1", "title": "경복궁 겨울", "tags": ["경복궁", "장안당", "서울"], "photographer": "a"},
            {"url": "u2", "title": "운현궁", "tags": ["운현궁", "노안당", "2025 대한민국 관광공모전(사진)"], "photographer": "b"},
        ]
        names = [t["name"] for t in pr.select_targets(photos, "건청궁", "", max_targets=10)]
        assert "경복궁" not in names and "장안당" in names
        assert not any("공모전" in n for n in names) and "노안당" in names

    def test_synonym_tags_sharing_same_photos_collapse_to_one(self):
        # 실측 결함 재현 3차: 같은 사진 4장에 함께 붙은 "먹자골목·먹자거리·이색거리"가 3타깃으로 나왔다.
        photos = [
            {"url": f"u{i}", "title": "세종마을 음식문화거리",
             "tags": ["먹자골목", "먹자거리", "이색거리"], "photographer": "a"} for i in range(4)
        ] + [{"url": "u9", "title": "세종마을 음식문화거리", "tags": ["금천교"], "photographer": "a"}]
        names = [t["name"] for t in pr.select_targets(photos, "세종마을 음식문화거리", "", max_targets=5)]
        assert len([n for n in names if n in ("먹자골목", "먹자거리", "이색거리")]) == 1
        assert "금천교" in names                       # 사진 집합이 다른 태그는 살아남는다

    def test_focused_photo_preferred_for_ref_image(self):
        photos = [
            {"url": "busy", "title": "운현궁", "tags": ["노안당", "노락당", "이로당"], "photographer": "a"},
            {"url": "focus", "title": "운현궁", "tags": ["노안당"], "photographer": "a"},
        ]
        t = pr.select_targets(photos, "운현궁", "", max_targets=1)[0]
        assert t["name"] == "노안당" and t["ref_image"] == "focus"

    def test_max_targets_respected_and_empty_when_nothing_specific(self):
        assert len(pr.select_targets(GALLERY, "경희궁", "", max_targets=1)) == 1
        assert pr.select_targets([GALLERY[5], GALLERY[6]], "경희궁", "", max_targets=3) == []


@pytest.mark.asyncio
class TestBuildPhotoRefs:
    async def test_full_path_detail_images_first(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "tourapi_service_key", "k")
        async def gallery(keyword, rows=60): return GALLERY
        async def detail(cid, rows=20): return [{"url": f"https://d/{i}.jpg", "name": f"경희궁 ({i})"} for i in range(8)]
        monkeypatch.setattr(pr, "gallery_photos", gallery)
        monkeypatch.setattr(pr, "detail_images", detail)
        monkeypatch.setattr(get_settings(), "photo_refs_max_images", 6)

        refs = await pr.build_photo_refs("경희궁", "1604784", OVERVIEW)
        assert refs["source"] == "detail"
        assert len(refs["ar_reference_images"]) == 6            # 상한 적용
        assert refs["ar_reference_images"][0] == "https://d/0.jpg"
        assert {t["name"] for t in refs["targets"]} <= {"흥화문", "숭정전", "숭정문", "자정문"}

    async def test_gallery_fallback_when_node_has_no_photos(self, monkeypatch):
        # 건청궁처럼 자기 사진이 0장인 노드 — 갤러리 사진으로라도 AR 참조를 채운다
        monkeypatch.setattr(get_settings(), "tourapi_service_key", "k")
        async def gallery(keyword, rows=60): return GALLERY[:3]
        async def detail(cid, rows=20): return []
        monkeypatch.setattr(pr, "gallery_photos", gallery)
        monkeypatch.setattr(pr, "detail_images", detail)
        refs = await pr.build_photo_refs("건청궁", "1604652", "")
        assert refs["source"] == "gallery"
        assert refs["ar_reference_images"] == ["https://x/1.jpg", "https://x/2.jpg", "https://x/3.jpg"]

    async def test_failures_never_raise(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "tourapi_service_key", "k")
        async def boom(*a, **k): raise RuntimeError("TourAPI down")
        monkeypatch.setattr(pr, "gallery_photos", boom)
        monkeypatch.setattr(pr, "detail_images", boom)
        refs = await pr.build_photo_refs("경희궁", "1604784", OVERVIEW)
        assert refs == {"targets": [], "ar_reference_images": [], "source": "none"}

    async def test_no_key_returns_empty_without_calls(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "tourapi_service_key", "")
        called = []
        async def gallery(*a, **k): called.append(1); return GALLERY
        monkeypatch.setattr(pr, "gallery_photos", gallery)
        refs = await pr.build_photo_refs("경희궁", "1", "")
        assert refs["source"] == "none" and not called


class TestMergeTargets:
    def test_text_bearing_llm_targets_stay_first(self):
        # 실측(경교장) 재현: LLM의 안내판·현판 타깃을 카탈로그 "개인 사저"가 덮어썼다
        out = pr.merge_targets(["대한민국 임시정부 전시공간 안내판", "백범 김구 선생 서거 역사적 현장 현판"], ["개인 사저"])
        assert out[:2] == ["대한민국 임시정부 전시공간 안내판", "백범 김구 선생 서거 역사적 현장 현판"]
        assert out[2] == "개인 사저"

    def test_generic_llm_targets_go_after_catalog(self):
        out = pr.merge_targets(["대문", "전통 건물 외관"], ["흥화문", "숭정전"])
        assert out == ["흥화문", "숭정전", "대문"]                  # 상한 3, 지어낸 일반어는 뒤로

    def test_dedupe_including_containment(self):
        out = pr.merge_targets(["흥화문 현판"], ["흥화문", "숭정전"])
        assert out == ["흥화문 현판", "숭정전"]                     # "흥화문"은 "흥화문 현판"에 포함 → 중복

    def test_seasonal_and_path_tags_blocked(self):
        photos = [{"url": "u", "title": "덕수궁 돌담길", "tags": ["정동길", "산책로", "추경", "둘레길"], "photographer": "a"}]
        names = [t["name"] for t in pr.select_targets(photos, "덕수궁 돌담길", "", max_targets=5)]
        assert names == ["정동길"]


@pytest.mark.asyncio
class TestAttach:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "photo_refs_enabled", True)

    async def test_disabled_flag_skips_tourapi_entirely(self, monkeypatch):
        monkeypatch.setattr(get_settings(), "photo_refs_enabled", False)
        called = []
        async def fake(*a): called.append(1); return {}
        monkeypatch.setattr(pr, "build_photo_refs", fake)
        m = {"type": "PHOTO_FIND", "photo_targets": ["대문"]}
        assert await pr.attach_photo_refs(m, {"name": "x"}) is m and not called

    async def test_merges_llm_and_catalog_and_keeps_llm_copy(self, monkeypatch):
        async def fake(name, cid, overview):
            return {"targets": [{"name": "흥화문", "why": None, "ref_image": "u", "credit": "c", "photo_count": 1}],
                    "ar_reference_images": ["a", "b"], "source": "detail"}
        monkeypatch.setattr(pr, "build_photo_refs", fake)
        mission = {"type": "PHOTO_FIND", "photo_targets": ["대문", "전통 건물 외관"]}
        out = await pr.attach_photo_refs(mission, {"name": "경희궁", "tour_content_id": "1", "node_id": "tour_1"})
        assert out["photo_targets"] == ["흥화문", "대문", "전통 건물 외관"]   # 문자열 계약 유지, 실존 명소가 앞
        assert out["llm_photo_targets"] == ["대문", "전통 건물 외관"]
        assert out["photo_refs"][0]["ref_image"] == "u"
        assert out["ar_reference_images"] == ["a", "b"]

    async def test_text_bearing_llm_target_not_overridden(self, monkeypatch):
        async def fake(name, cid, overview):
            return {"targets": [{"name": "개인 사저", "why": None, "ref_image": "u", "credit": "c", "photo_count": 1}],
                    "ar_reference_images": [], "source": "gallery"}
        monkeypatch.setattr(pr, "build_photo_refs", fake)
        out = await pr.attach_photo_refs({"type": "PHOTO_FIND", "photo_targets": ["백범 서거 현장 현판"]}, {"name": "서울 경교장"})
        assert out["photo_targets"][0] == "백범 서거 현장 현판"

    async def test_keeps_llm_targets_when_catalog_empty(self, monkeypatch):
        async def fake(name, cid, overview):
            return {"targets": [], "ar_reference_images": ["a"], "source": "gallery"}
        monkeypatch.setattr(pr, "build_photo_refs", fake)
        out = await pr.attach_photo_refs({"type": "PATH_TRACE", "photo_targets": ["전경"]}, {"name": "x"})
        assert out["photo_targets"] == ["전경"] and "llm_photo_targets" not in out
        assert out["ar_reference_images"] == ["a"]

    async def test_other_types_untouched(self, monkeypatch):
        called = []
        async def fake(*a): called.append(1); return {}
        monkeypatch.setattr(pr, "build_photo_refs", fake)
        m = {"type": "HUNT", "count": 5}
        assert await pr.attach_photo_refs(m, {"name": "x"}) is m and not called
