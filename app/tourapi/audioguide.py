# ============================================================
# [v1] TourAPI 오디오가이드 클라이언트 — 관광지 대본 텍스트(grounding 원천)
# pipeline: AI 백엔드 / 외부 데이터 (노드 텍스트: NPC 대화 grounding 3단계)
# 구현(요약): 공통 호출부(base.request_all) 위 골격만. ⚠️ 서비스명/오퍼레이션/파라미터·
#            응답 필드는 스펙 미확정 → _SERVICE/_OP/파라미터 확정 후 _to_texts 채울 것.
# 구현일: 2026-06-18 | 작성: kys (audioguide-client/kys/v1)
# ============================================================
from app.config import get_settings
from app.tourapi.base import TourAPIError, request_all

# ⚠️ TODO(스펙 확정): 공공데이터포털 "관광지 오디오가이드" 서비스명·오퍼레이션명
#    예상 구조 GET {root}/{_SERVICE}/{_OP}. 빅데이터 문서처럼 실제 값 확인 후 교체.
_SERVICE = ""   # 예: "KorAudioGuideService" (미확정)
_OP = ""        # 예: "audioGuideList" / "themeBasedList" 등 (미확정)


class AudioGuideClient:
    """관광지 오디오가이드(대본 텍스트) 클라이언트.

    오디오가이드 대본 = NPC 대화 grounding 주원천(긴 텍스트면 청킹·임베딩 대상, 1-1).
    ⚠️ 현재 스펙 미확정 — 서비스명/파라미터 확인 전까지 호출 불가.
    """

    def __init__(self) -> None:
        self._root = get_settings().tourapi_data_base_url.rstrip("/")

    async def list_by_area(self, area_cd: str, signgu_cd: str, rows: int = 100) -> list[dict]:
        """[골격] 지역 오디오가이드 목록/대본. 스펙 확정 후 파라미터·반환 정규화 채움."""
        if not (_SERVICE and _OP):
            raise TourAPIError(
                "오디오가이드 스펙 미확정 — 서비스명/오퍼레이션/파라미터 확인 필요"
                " (공공데이터포털 '관광지 오디오가이드' 문서)"
            )
        # TODO(스펙 확정): 실제 파라미터명으로 교체 (areaCd/signguCd 또는 contentId 기반?)
        items = await request_all(f"{self._root}/{_SERVICE}", _OP, {
            "areaCd": area_cd, "signguCd": signgu_cd, "numOfRows": rows,
        })
        return self._to_texts(items)

    def _to_texts(self, items: list[dict]) -> list[dict]:
        """[골격] 오디오가이드 item → {node 매칭키, script_text} 정규화. 스펙 확정 후 채움.

        반환 예상: {"name": ..., "script_text": ...} → nodes.audio_guide_text 로 적재.
        """
        # TODO(스펙 확정): 실제 응답 필드명(대본 텍스트·관광지명/코드)으로 매핑
        return items
