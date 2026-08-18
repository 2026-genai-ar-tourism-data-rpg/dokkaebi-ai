# ============================================================
# [v2] 종로 고정 스크립트 — PDF 정답지 재생 (전면 재작성)
# scenario: 종로 지역 (「종로, 꺼져가는 글빛의 봉인」)
# 구현(요약): 게임_전반_스토리라인.pdf(§3 종로 MVP)를 그대로 옮김.
#            프롤로그(안국역) + 5개 조각 노드 + 최종노드(광화문/세종대왕상), 총 7개 항목.
#            generate_scenario에서 region=="종로" 분기로 동적 파이프라인 우회.
#            validate_app_contract가 검증하는 필드(motivation/strategy/actions/
#            hint_ladder/grants/requires)는 화이트리스트에 맞추고, PDF의 풍부한 원문
#            (선택지별 NPC 응답, 정원 보상, 엔딩 분기 등)은 별도 부가 필드로 보존.
# ------------------------------------------------------------
# v1(baseline-v1.1 기준, 조각 3개·이순신 사이드)은 사용자가 준 PDF와 내용이 달라 폐기.
# PDF §3 인사동길 퀴즈("'ㄱ'+소리→가") 는 단서 체인(처마3보→溫茶→三墨→손의결→글빛五序)과
# 'ㄱ' 단서가 이 스크립트 안에서 대응되지 않는 PDF 자체의 표기 불일치 — 수정하지 않고
# 원문 그대로 옮김(콘텐츠 판단은 담당자 몫, 발견 사항으로만 기록).
# 구현일: 2026-08-18 | 작성: 정찬희
# ============================================================
from typing import Any


# --- 노드 좌표(실제 공개 데이터, lat/lng) ---
NODES_GEO = {
    "tour_anguk": {"lat": 37.5765, "lng": 126.9853},            # 안국역(프롤로그)
    "tour_unhyeongung": {"lat": 37.5745, "lng": 126.9858},      # 운현궁
    "tour_ikseondong": {"lat": 37.5740, "lng": 126.9905},       # 익선동 한옥카페
    "tour_insadong": {"lat": 37.5740, "lng": 126.9856},         # 인사동길
    "tour_gongye": {"lat": 37.5765, "lng": 126.9800},           # 서울공예박물관
    "tour_bukchon": {"lat": 37.5826, "lng": 126.9850},          # 북촌한옥마을
    "tour_gwanghwamun": {"lat": 37.5728, "lng": 126.9766},      # 광화문광장/세종대왕상
}

# 글빛 五序(정답 배치 순서) — 최종노드에서 이 순서대로 조각을 놓아야 복원됨.
FINAL_ORDER = [
    "종로_stone_1of5",  # 먹빛
    "종로_stone_2of5",  # 온기
    "종로_stone_3of5",  # 붓끝
    "종로_stone_4of5",  # 손결
    "종로_stone_5of5",  # 처마빛
]

_EMPTY_LADDER: dict[str, Any] = {"open_rule": []}


def _choice(label: str, text: str) -> dict[str, Any]:
    """선택지 빌더 — validate_app_contract 화이트리스트(id/text)만 사용."""
    return {"id": label, "text": text}


def build_quest_0_prologue() -> dict[str, Any]:
    """0. 프롤로그 — 안국역 근처. NPC: 초롱 도깨비."""
    return {
        "order": 0,
        "node_id": "tour_anguk",
        "name": "안국역 근처",
        "kind": "spot",
        "map_x": NODES_GEO["tour_anguk"]["lng"],
        "map_y": NODES_GEO["tour_anguk"]["lat"],
        "dist_m": 1.0,
        "density_tier": None,
        "source": "jongno_script",
        "out_of_radius": False,
        "trigger_radius_m": 100,
        "stone_no": None,
        "fragment_id": None,
        "is_finale": False,
        "npc": {
            "name": "초롱 도깨비",
            "archetype": "guide",
            "motif": "초롱불, 푸른 기억의 빛",
            "persona": "겁먹은 플레이어를 달래지만, 상황을 숨기지 않는 첫 길잡이 도깨비.",
        },
        "npc_dialogue": (
            "드디어... 우리를 볼 수 있는 인간이 나타났구나.\n"
            "우리는 이 땅의 기억을 지키던 도깨비니라. 오래된 궁과 골목, 사람들의 말과 손길을 지켜 왔지.\n"
            "네가 본 것은 기억의 빛이니라. 사람들이 잊은 장소의 힘을 먹고 자라는 망각귀가 이 땅의 글빛 기억석을 "
            "깨뜨렸고, 그 빛이 네 눈에 깃들었다. 이제 너는 인간들이 잊어버린 것들을 보게 되었느니라.\n"
            "돌아갈 방법은 있다. 흩어진 기억석 조각을 모아 망각귀의 봉인을 되살리면, 네 눈에 깃든 도깨비의 "
            "기운도 거두어 주마.\n"
            "탐사자여, 두렵겠지만 우리를 도와다오. 이곳의 기억이 완전히 사라지기 전에, 첫 번째 조각을 찾아야 "
            "하느니라. 첫 번째 조각은 운현궁에 숨어 있느니라. 운현궁으로 가보아라."
        ),
        "motivation": ["M1"],
        "strategy": ["S1_TALK_GATHER"],
        "actions": [
            {"a": "goto", "place": "안국역 근처"},
            {"a": "tap", "target": "푸른 빛"},
            {"a": "listen", "slot": "intro", "choices": []},  # 프롤로그는 컷신형 대화 — 분기 선택지 없음
            {"a": "unlock_marker", "place": "운현궁"},
        ],
        "mission": None,
        "quiz": None,
        "objective": None,
        "requires": [],
        "requires_mode": "none",
        "grants": ["clue:처마3보"],
        "clue": "처마3보",
        "clue_text": "첫 기억은 높은 곳에 숨지 않는다. 오래된 집의 처마 아래, 먹빛 발자국이 세 걸음 남아 있느니라. 이 단서를 기억하거라. 처마 3보.",
        "success": ["place_verified", "listen_done"],
        "hint_ladder": _EMPTY_LADDER,
        "codex_npc": "초롱 도깨비",
        "codex_condition": "none",
    }


def build_quest_1_unhyeongung() -> dict[str, Any]:
    """1. 운현궁 — 먹 도깨비. 글빛 조각 1: 먹빛 조각."""
    return {
        "order": 1,
        "node_id": "tour_unhyeongung",
        "name": "운현궁",
        "kind": "spot",
        "map_x": NODES_GEO["tour_unhyeongung"]["lng"],
        "map_y": NODES_GEO["tour_unhyeongung"]["lat"],
        "dist_m": 1.0,
        "density_tier": None,
        "source": "jongno_script",
        "out_of_radius": False,
        "trigger_radius_m": 100,
        "stone_no": 1,
        "fragment_id": "종로_stone_1of5",
        "is_finale": False,
        "npc": {
            "name": "먹 도깨비",
            "archetype": "guardian",
            "motif": "붓, 먹, 오래된 글씨",
            "persona": "옛 글을 지키는 과묵하고 위엄 있는 도깨비.",
        },
        "npc_dialogue": "허허, 초롱이가 보낸 인간이 자네로구나. 이 땅의 기억 한 조각이 먹물 속으로 숨어버렸느니라. 자네, 눈썰미가 좋은가?",
        "motivation": ["M1", "M7"],
        "strategy": ["S4_PHOTO_TRAIL", "S3_RIDDLE_UNLOCK"],
        "actions": [
            {"a": "goto", "place": "운현궁"},
            {
                "a": "listen",
                "slot": "intro+choices",
                "choices": [_choice("A", "운현궁은 어떤 곳이오?"), _choice("B", "왜 글빛 조각을 숨긴 거야?"),
                            _choice("C", "좋아, 첫 조각을 찾아볼게.")],
            },
            {"a": "capture", "targets": ["대문", "처마", "전통건물 외관"]},
            {"a": "follow", "object": "먹물 발자국", "steps": 3},
            {"a": "tap", "target": "먹빛 조각"},
            {"a": "answer", "quiz": {"answer_idx": 1}},
        ],
        "choice_responses": {
            "A": {"role": "장소정보질문", "response": "흥선대원군이 머물던 사저로 알려진 곳이니라. 권세와 기록의 기운이 오래 남아 있는 터지."},
            "B": {"role": "스토리정보질문", "response": "글은 권세가 아니라 기억을 남기는 힘이니라. 망각귀는 그 힘부터 지우려 하였지."},
            "C": {"role": "다음액션진행", "response": "처마 3보를 알고 왔구나. 그럼 처마를 화면에 담아 보거라. 대문이나 처마를 화면에 들이면 먹물 발자국 셋이 첫 글빛으로 이끌 것이니라."},
        },
        "mission": {
            "type": "photo_trail",
            "order": "PHOTO_TRAIL",
            "steps": ["GPS 인증", "AR 카메라 실행", "대문/처마/전통건물 외관 촬영 인증",
                      "검은 먹물 발자국 등장", "발자국 3개 추적", "먹빛 조각 탭", "퀴즈 정답"],
        },
        "quiz": {
            "question": "이 집의 주인을 알아야 글씨가 모습을 드러내느니. 운현궁과 관련 깊은 인물은 누구더냐?",
            "options": ["세종대왕", "흥선대원군", "이순신"],
            "answer_idx": 1,
        },
        "objective": {"order": "PHOTO_TRAIL", "hints": ["처마 아래를 살펴보거라", "먹물 발자국 3개를 따라가거라"]},
        "requires": ["clue:처마3보"],
        "requires_mode": "soft",
        "grants": ["fragment:종로_stone_1of5", "clue:溫茶"],
        "clue": "溫茶",
        "clue_text": "먹빛은 찾았으나 아직 글자가 차갑구나. 글은 사람의 온기를 만나야 다시 살아나는 법. 다음 조각은 溫茶, 따뜻한 차의 김 속에서 깨어날 게다.",
        "success": ["place_verified", "photo_done", "follow:먹물 발자국>=3", "quiz_correct", "tap:먹빛 조각"],
        "hint_ladder": {
            "H1": "발자국은 해 지는 쪽으로 번졌느니",
            "H2": "이로당 처마 아래니라",
            "H3": "처마 그늘 왼편, 세 번째 서까래",
            "open_rule": ["fail1|idle60", "idle90", "button"],
        },
        "garden_reward": {"item": "먹빛 발자국 둘길", "type": "바닥 장식",
                           "desc": "AR에서 따라갔던 먹물 발자국이 정원 길로 변한 아이템"},
        "codex_npc": "먹 도깨비",
        "codex_condition": "talk1",  # 최소 NPC와의 대화 1회 진행 후 등록
    }


def build_quest_2_ikseondong() -> dict[str, Any]:
    """2. 익선동 한옥카페 — 온기 도깨비. 글빛 조각 2: 온기 조각. (식음 노드지만 kind=spot 필수)"""
    return {
        "order": 2,
        "node_id": "tour_ikseondong",
        "name": "익선동 한옥카페",
        "kind": "spot",  # food/cafe면 validate_app_contract가 조각 grants를 막음
        "map_x": NODES_GEO["tour_ikseondong"]["lng"],
        "map_y": NODES_GEO["tour_ikseondong"]["lat"],
        "dist_m": 1.0,
        "density_tier": None,
        "source": "jongno_script",
        "out_of_radius": False,
        "trigger_radius_m": 100,
        "stone_no": 2,
        "fragment_id": "종로_stone_2of5",
        "is_finale": False,
        "npc": {
            "name": "온기 도깨비",
            "archetype": "guardian",
            "motif": "찻잔, 기와, 온기",
            "persona": "익선동 골목의 온기와 웃음소리를 지키는 도깨비.",
        },
        "npc_dialogue": "골목이 소란하니 차 한 잔의 온기가 필요하지. 망각귀가 지나간 뒤로 이 골목의 웃음소리가 옅어졌느니라. 장터와 골목이 살아야 기억도 사느니.",
        "motivation": ["M4", "M6"],
        "strategy": ["S7_PATRONIZE", "S1_TALK_GATHER"],
        "actions": [
            {"a": "goto", "place": "익선동 한옥카페"},
            {
                "a": "listen",
                "slot": "intro+choices",
                "choices": [_choice("A", "이 골목은 왜 한옥이 많아?"), _choice("B", "차 한 잔이 왜 기억을 되살리지?"),
                            _choice("C", "좋아, 주문하고 확인할게.")],
            },
            {"a": "purchase", "menu": "따뜻한 음료", "verification": "receipt_or_order"},
            {"a": "capture", "targets": ["찻잔", "테이블 주변"]},
            {"a": "tap", "target": "온기 조각"},
            {"a": "report", "npc": "온기 도깨비"},
        ],
        "choice_responses": {
            "A": {"role": "장소정보질문", "response": "오래된 한옥들이 골목의 결을 만들고, 사람들은 그 안에서 쉬고 이야기하며 기억을 남겼느니라."},
            "B": {"role": "스토리정보질문", "response": "사람이 머무는 곳에 온기가 남고, 온기가 남은 곳에 이야기가 붙는 법이니라."},
            "C": {"role": "다음액션진행", "response": "溫茶를 품고 왔구나. 따뜻한 음료의 김이 오르면, 그 위에 도깨비눈을 비추어 보거라. 숨어 있던 획이 떠오를 것이니라."},
        },
        "mission": {
            "type": "purchase_ar",
            "order": "PATRONIZE_AR",
            "steps": ["노드 반경 진입", "따뜻한 음료 주문 인증", "쿠폰 500원 사용",
                      "AR 카메라로 찻잔/테이블 확인", "찻잔 김 사이 조각 탭", "완료 보고"],
        },
        "quiz": None,  # PDF: 이 노드는 AR 탐색만, 퀴즈 없음
        "objective": {"order": "PATRONIZE_AR", "hints": ["따뜻한 음료를 주문해 보거라", "찻잔의 김을 비추어 보거라"]},
        "budget": {"expected": 6000, "coupon": -500, "actual": 5500, "note": "익선동 음료 — 운현궁 보상쿠폰 사용"},
        "requires": ["clue:溫茶"],
        "requires_mode": "soft",
        "grants": ["fragment:종로_stone_2of5", "clue:三墨", "coupon:인사동:1000"],
        "clue": "三墨",
        "clue_text": "찻잔의 김 속에서 획 하나가 깨어났구나. 하지만 붓끝은 아직 셋으로 흩어져 있다. 골목의 글씨 사이에 숨은 三墨을 찾아야 하느니라.",
        "success": ["place_verified", "purchase_verified", "tap:온기 조각"],
        "hint_ladder": _EMPTY_LADDER,
        "garden_reward": {"item": "온기 찻상 세트", "type": "가구 / 휴식 공간",
                           "desc": "찻잔, 작은 나무 상, 따뜻한 김이 피어오르는 장식"},
        "codex_npc": "온기 도깨비",
        "codex_condition": "affinity",  # 친밀도가 쌓여야 등록(다른 노드보다 조건이 더 까다로움)
    }


def build_quest_3_insadong() -> dict[str, Any]:
    """3. 인사동길 — 붓장수 도깨비. 글빛 조각 3: 붓끝 조각."""
    return {
        "order": 3,
        "node_id": "tour_insadong",
        "name": "인사동길",
        "kind": "spot",
        "map_x": NODES_GEO["tour_insadong"]["lng"],
        "map_y": NODES_GEO["tour_insadong"]["lat"],
        "dist_m": 1.0,
        "density_tier": None,
        "source": "jongno_script",
        "out_of_radius": False,
        "trigger_radius_m": 100,
        "stone_no": 3,
        "fragment_id": "종로_stone_3of5",
        "is_finale": False,
        "npc": {
            "name": "붓장수 도깨비",
            "archetype": "guardian",
            "motif": "붓, 간판, 장터, 공예품",
            "persona": "잃어버린 붓방망이를 찾는, 장터의 글씨를 지키는 도깨비.",
        },
        "npc_dialogue": "아이고, 큰일 났네. 내 붓방망이를 잃어버렸지 뭔가. 그 붓끝에 글빛 조각이 묻어 있었는데, 먹그림자들이 먹방울로 쪼개 가져갔느니라.",
        "motivation": ["M8", "M7"],
        "strategy": ["S6_ACCUMULATE", "S3_RIDDLE_UNLOCK"],
        "actions": [
            {"a": "goto", "place": "인사동길"},
            {
                "a": "listen",
                "slot": "intro+choices",
                "choices": [_choice("A", "인사동은 어떤 곳이야?"), _choice("B", "붓방망이가 왜 중요해?"),
                            _choice("C", "먹방울을 찾아볼게.")],
            },
            {"a": "capture", "targets": ["전통 간판", "골목 장식"]},
            {"a": "collect", "target": "먹방울", "count": 3},
            {"a": "answer", "quiz": {"answer_idx": 0}},
            {"a": "tap", "target": "붓끝 조각"},
        ],
        "choice_responses": {
            "A": {"role": "장소정보질문", "response": "글씨와 그림, 공예와 물건들이 오가는 길이니라. 사람의 손으로 만든 것들이 기억을 품고 있지."},
            "B": {"role": "스토리정보질문", "response": "글빛 조각을 한데 묶는 도구니라. 그것이 없으면 마지막 봉인도 흐트러질 수 있지."},
            "C": {"role": "다음액션진행", "response": "좋다, 三墨이라... 허허, 제대로 알고 왔구먼. 간판과 붓글씨 사이에 먹방울 셋이 숨어 있네. 셋을 모으면 잠긴 붓상자가 열릴 게야."},
        },
        "mission": {
            "type": "accumulate",
            "order": "ACCUMULATE",
            "steps": ["GPS 인증", "AR 카메라 실행", "전통 간판/골목 장식 주변 먹방울 3개 수집",
                      "잠긴 붓상자 등장", "퀴즈 정답", "붓끝 조각 탭"],
        },
        "quiz": {
            # PDF 원문 그대로 — 'ㄱ' 단서는 이 스크립트의 단서 체인(溫茶/三墨)과 대응되지 않는
            # PDF 자체의 표기 불일치. 임의 수정하지 않고 원문 유지.
            "question": "운현궁에서 얻은 단서 'ㄱ'에, 익선동의 온기가 비춘 소리를 더하면 어떤 첫 글자가 되겠느냐?",
            "options": ["가", "나", "다"],
            "answer_idx": 0,
        },
        "objective": {"order": "ACCUMULATE", "hints": ["간판과 붓글씨 사이를 살펴보거라", "먹방울 3개를 모으거라"]},
        "requires": ["clue:三墨"],
        "requires_mode": "soft",
        "grants": ["fragment:종로_stone_3of5", "clue:손의결"],
        "clue": "손의결",
        "clue_text": "먹방울은 모았지만, 붓끝만으로는 글빛을 묶을 수 없네. 글도, 물건도, 결국 손을 지나야 남는 법이지. 다음에는 손의 결을 찾아가게.",
        "success": ["place_verified", "collect:먹방울>=3", "quiz_correct", "tap:붓끝 조각"],
        "hint_ladder": _EMPTY_LADDER,
        "bonus_xp": {"condition": "인사동쿠폰 사용", "amount": 10},
        "garden_reward": {"item": "붓꽃 화단", "type": "식물 / 화단",
                           "desc": "붓끝 모양의 꽃이 피는 화단. 글빛 테마와 직접 연결"},
        "codex_npc": "붓장수 도깨비",
        "codex_condition": "talk1",
    }


def build_quest_4_gongye() -> dict[str, Any]:
    """4. 서울공예박물관 — 손끝 도깨비. 글빛 조각 4: 손결 조각."""
    return {
        "order": 4,
        "node_id": "tour_gongye",
        "name": "서울공예박물관",
        "kind": "spot",
        "map_x": NODES_GEO["tour_gongye"]["lng"],
        "map_y": NODES_GEO["tour_gongye"]["lat"],
        "dist_m": 1.0,
        "density_tier": None,
        "source": "jongno_script",
        "out_of_radius": False,
        "trigger_radius_m": 100,
        "stone_no": 4,
        "fragment_id": "종로_stone_4of5",
        "is_finale": False,
        "npc": {
            "name": "손끝 도깨비",
            "archetype": "guardian",
            "motif": "손, 실, 도구, 공예",
            "persona": "손끝으로 새기고 다듬은 것들에 깃든 기억을 지키는 도깨비.",
        },
        "npc_dialogue": "글은 눈으로만 남는 것이 아니니라. 누군가의 손끝으로 새기고, 묶고, 다듬은 것에도 기억이 깃들지. 망각귀가 그 손의 결을 흐려 놓았구나.",
        "motivation": ["M1", "M8"],
        "strategy": ["S5_PHOTO_PROOF", "S6_ACCUMULATE"],
        "actions": [
            {"a": "goto", "place": "서울공예박물관"},
            {
                "a": "listen",
                "slot": "intro+choices",
                "choices": [_choice("A", "공예에도 기억이 깃들 수 있어?"), _choice("B", "왜 글빛 조각이 공예와 연결돼?"),
                            _choice("C", "손의 결을 찾아볼게.")],
            },
            {"a": "capture", "targets": ["박물관 외관", "안내 표식", "마당 오브젝트"]},
            {"a": "collect", "target": "손결 파편", "count": 4},
            {"a": "tap", "target": "손결 조각"},
        ],
        "choice_responses": {
            "A": {"role": "장소정보질문", "response": "물건은 사람의 시간을 품느니라. 손때와 흠집도 모두 기억의 무늬지."},
            "B": {"role": "스토리정보질문", "response": "글을 남기는 것도 손의 일이고, 물건을 만드는 것도 손의 일이니라. 둘은 같은 결을 타고 흐른다."},
            "C": {"role": "다음액션진행", "response": "손의 결을 알고 왔구나. 그럼 사람의 손길이 남은 외관과 안내 표식을 먼저 확인하거라. 결 파편 네 조각이 모습을 드러낼 것이니라."},
        },
        "mission": {
            "type": "photo_proof_accumulate",
            "order": "PHOTO_ACCUMULATE",
            "steps": ["반경 진입 후 GPS 인증", "박물관 외관/안내 표식/마당 오브젝트 촬영 인증",
                      "AR로 손결 파편 4개 등장", "파편 4개 수집", "파편 합체 → 손결 조각 생성", "탭"],
        },
        "quiz": None,  # PDF: 이 노드도 AR 수집만, 퀴즈 없음
        "objective": {"order": "PHOTO_ACCUMULATE", "hints": ["박물관 외관과 안내 표식을 촬영하거라", "손결 파편 4개를 모으거라"]},
        "requires": ["clue:손의결"],
        "requires_mode": "soft",
        "grants": ["fragment:종로_stone_4of5", "clue:처마매듭"],
        "clue": "처마매듭",
        "clue_text": "손의 결은 이어졌지만, 먹그림자가 글빛을 물고 달아났구나. 그놈들은 처마선에 봉인을 묶어 두었느니라. 먼저 처마 매듭을 풀어야 먹그림자를 쫓을 수 있다.",
        "success": ["place_verified", "photo_done", "collect:손결 파편>=4", "tap:손결 조각"],
        "hint_ladder": _EMPTY_LADDER,
        "bonus_xp": {"condition": "인사동쿠폰 사용", "amount": 10},
        "garden_reward": {"item": "손결 작업대", "type": "제작대 / 장식물",
                           "desc": "실타래, 나무 도구, 작은 공예품이 놓인 작업대"},
        "codex_npc": "손끝 도깨비",
        "codex_condition": "talk1",
    }


def build_quest_5_bukchon() -> dict[str, Any]:
    """5. 북촌한옥마을 — 처마 도깨비. 글빛 조각 5: 처마빛 조각."""
    return {
        "order": 5,
        "node_id": "tour_bukchon",
        "name": "북촌한옥마을",
        "kind": "spot",
        "map_x": NODES_GEO["tour_bukchon"]["lng"],
        "map_y": NODES_GEO["tour_bukchon"]["lat"],
        "dist_m": 1.0,
        "density_tier": None,
        "source": "jongno_script",
        "out_of_radius": False,
        "trigger_radius_m": 100,
        "stone_no": 5,
        "fragment_id": "종로_stone_5of5",
        "is_finale": False,
        "npc": {
            "name": "처마 도깨비",
            "archetype": "guardian",
            "motif": "처마, 골목, 집의 숨",
            "persona": "사람들이 살아가는 골목의 평온을 지키는, 조용하고 신중한 도깨비.",
        },
        "npc_dialogue": "쉿, 목소리를 낮추거라. 이곳은 사람들이 살아가는 골목이니라. 먹그림자가 처마에 번졌구나. 다섯 마리를 쫓아내야 마지막 글빛이 드러날 것이니라.",
        "motivation": ["M2", "M5", "M9"],
        "strategy": ["S2_HUNT_GATHER", "S5_PHOTO_PROOF"],
        "actions": [
            {"a": "goto", "place": "북촌한옥마을"},
            {
                "a": "listen",
                "slot": "intro+choices",
                "choices": [_choice("A", "북촌은 왜 조용히 해야 해?"), _choice("B", "저 도깨비 잔영들은 누구야?"),
                            _choice("C", "먹그림자를 쫓아낼게.")],
            },
            {"a": "capture", "targets": ["공개 골목의 처마선", "하늘 방향"]},
            {"a": "defeat", "target": "먹그림자", "count": 5},
            {"a": "tap", "target": "처마선 매듭", "count": 3},
            {"a": "tap", "target": "처마빛 조각"},
            {"a": "report", "npc": "도깨비 잔영", "kind": "전언"},
        ],
        "choice_responses": {
            "A": {"role": "장소정보질문", "response": "이곳은 관광지이면서도 누군가의 일상이 이어지는 마을이니라. 기억을 지키려면 사람의 삶도 함께 지켜야 하지."},
            "B": {"role": "스토리정보질문", "response": "집과 골목을 지키던 작은 도깨비들이니라. 망각귀에게 이름을 빼앗겨 제 터를 잊어가고 있지."},
            "C": {"role": "다음액션진행", "response": "좋다. 처마 매듭을 알고 왔구나. 먼저 매듭 셋을 풀어라. 그래야 다섯 먹그림자의 힘이 약해질 것이니라."},
        },
        "mission": {
            "type": "hunt_gather",
            "order": "HUNT_GATHER",
            "steps": ["GPS 인증", "AR 카메라 실행", "공개 골목 처마선/하늘 방향 촬영 인증",
                      "먹그림자 5마리 등장", "처마선 촬영 → 매듭 탭 해제 x3",
                      "먹그림자 5마리 정화 후 처마빛 조각 등장", "조각 탭", "도깨비 잔영에게 전언 전달"],
        },
        "quiz": None,
        "objective": {"order": "HUNT_GATHER", "hints": ["처마선을 촬영해 매듭을 풀거라", "먹그림자 5마리를 정화하거라"]},
        "farewell_scene": [
            {"speaker": "도깨비 잔영", "line": "내가 지키던 집의 이름을… 이제야 기억하겠구나."},
            {"speaker": "처마 도깨비", "line": "고맙다, 탐사자여. 네가 찾은 것은 조각 하나가 아니라, 누군가의 돌아갈 자리니라."},
        ],
        "requires": ["clue:처마매듭"],
        "requires_mode": "soft",
        "grants": ["fragment:종로_stone_5of5", "clue:글빛五序"],
        "clue": "글빛五序",
        "clue_text": "먹그림자를 쫓아내니, 흩어진 글빛의 길이 보이는구나. 잘 기억하거라. 글은 먹에서 시작해, 온기를 만나고, 붓끝을 지나, 손의 결로 남으며, 마지막엔 집의 처마 아래 머무른다. 이것이 글빛 五序니라.",
        "success": ["place_verified", "photo_done", "defeat:먹그림자>=5", "tap:처마선 매듭>=3", "tap:처마빛 조각"],
        "hint_ladder": _EMPTY_LADDER,
        "garden_reward": {"item": "처마 등롱", "type": "조명 / 한옥 장식",
                           "desc": "한옥 처마 아래 매다는 작은 등롱. 밤 정원 연출에 사용"},
        "codex_npc": "처마 도깨비",
        "codex_condition": "talk1",
    }


def build_quest_6_gwanghwamun_finale() -> dict[str, Any]:
    """6. 최종노드 — 광화문광장/세종대왕상. NPC: 글빛 수호 도깨비. 최종목표: 글빛 조각 5개 합성."""
    ending_a = {
        "id": "A",
        "choice_text": "이제 조금은 알 것 같아. 기억을 지키는 이유를.",
        "ending": "굿 엔딩",
        "npc_dialogue": [
            "그 말을 들으니, 종로의 글빛도 한결 밝아지는구나.",
            "탐사자여, 기억을 지킨다는 것은 오래된 것을 붙잡는 일이 아니다. 누군가의 이름과 발자국이 아무 "
            "의미 없이 사라지지 않게 하는 일이지.",
            "오늘 그대는 종로의 기억석을 복원했다. 그러나 이것은 팔도 봉인의 첫 글자에 지나지 않는다.",
            "망각귀의 본체를 봉인하려면, 앞으로 다른 지역에 흩어진 기억석도 되살려야 하느니라. 각 지역의 "
            "기억석을 복원할 때마다, 네 눈에 깃든 도깨비의 기운도 조금씩 안정될 것이다.",
            "다음 조건은 이것이다. 팔도 기억 지도에 새로 떠오른 빛을 따라가라. 그곳의 수호 도깨비를 만나고, "
            "그 지역의 기억석 조각을 모두 모아라.",
            "네가 기억을 외면하지 않는 한, 도깨비들도 너를 외면하지 않을 것이다. 이제 너는 단순히 우리를 "
            "보는 인간이 아니라, 기억을 이어 쓰는 탐사자니라.",
        ],
        "rewards": {
            "title": "종로의 글빛 복원자",
            "garden_item_final": "종로 글빛 기억석",
            "garden_items_per_node": ["먹빛 발자국 둘길", "온기 찻상 세트", "붓꽃 화단", "손결 작업대", "처마 등롱"],
            "unlock": "팔도 기억 지도 — 다음 지역의 기억빛이 희미하게 떠오릅니다.",
        },
    }
    ending_b = {
        "id": "B",
        "choice_text": "그래도 난 아직 평범하게 돌아가고 싶어.",
        "ending": "노멀 엔딩",
        "npc_dialogue": [
            "두려워하는 마음을 부끄러워하지 말거라. 인간이 보지 않아도 될 것들을 보게 되었으니, 그 마음 "
            "또한 당연하니라.",
            "약속은 지키겠다. 종로의 기억석이 복원되었으니, 네 눈에 깃든 도깨비의 기운도 조금은 가라앉을 것이다.",
            "하지만 아직 완전히 거둘 수는 없다. 망각귀의 봉인은 종로 하나로 완성되는 것이 아니니라. 팔도 "
            "곳곳의 기억석이 함께 이어져야 비로소 네 눈도 다시 평범한 인간의 눈으로 돌아갈 수 있다.",
            "다음 조건은 분명하다. 팔도 기억 지도에 나타난 다음 지역으로 향하라. 그곳의 기억석 조각을 모으고, "
            "지역 수호 도깨비의 봉인을 되살려라.",
            "원한다면 도망쳐도 된다. 하지만 네가 다시 평범해지고 싶다면, 이 길을 끝까지 걸어야 하느니라.",
            "걱정 말거라. 다음 여정에서도 우리는 네 곁에 있을 것이다.",
        ],
        "rewards": {
            "title": "종로의 글빛 복원자",
            "garden_item_final": "종로 글빛 기억석",
            "garden_items_per_node": [],  # 노멀 엔딩은 노드별 정원 아이템 없음(PDF 그대로)
            "unlock": "팔도 기억 지도 — 다음 지역의 기억빛이 희미하게 떠오릅니다.",
        },
    }

    return {
        "order": 6,
        "node_id": "tour_gwanghwamun",
        "name": "광화문광장 / 세종대왕상",
        "kind": "spot",
        "map_x": NODES_GEO["tour_gwanghwamun"]["lng"],
        "map_y": NODES_GEO["tour_gwanghwamun"]["lat"],
        "dist_m": 1.0,
        "density_tier": None,
        "source": "jongno_script",
        "out_of_radius": False,
        "trigger_radius_m": 100,
        "stone_no": None,
        "fragment_id": None,
        "is_finale": True,
        "npc": {
            "name": "글빛 수호 도깨비",
            "archetype": "guardian",
            "motif": "세종, 글, 백성, 빛",
            "persona": "종로 전체의 글빛 기억석을 지키는 최종 수호 도깨비.",
        },
        "npc_dialogue": "그대가 흩어진 글빛을 모두 모아 왔는가. 임금의 글이 잠들어선 아니 되네. 글은 누군가의 이름을 부르고, 잊힌 이를 다시 기억하게 하는 힘이니라.",
        "motivation": ["M3", "M1"],
        "strategy": ["S1_TALK_GATHER", "S6_ACCUMULATE"],
        "actions": [
            {"a": "goto", "place": "광화문광장"},
            {
                "a": "listen",
                "slot": "intro+choices",
                "choices": [_choice("A", "왜 글이 그렇게 중요해?"), _choice("B", "망각귀를 봉인하면 나는 돌아갈 수 있어?"),
                            _choice("C", "글빛 기억석을 복원할게.")],
            },
            {"a": "capture", "targets": ["광화문광장 전경"]},
            {"a": "combine", "items": FINAL_ORDER, "order_required": True, "hold": True},
            {
                "a": "listen",
                "slot": "ending_choice",
                "choices": [_choice("A", ending_a["choice_text"]), _choice("B", ending_b["choice_text"])],
            },
        ],
        "choice_responses": {
            "A": {"role": "장소/역사정보질문", "response": "말과 글은 사람을 기억하게 하느니라. 이름을 잃은 자도, 기록으로 다시 불릴 수 있지."},
            "B": {"role": "스토리정보질문", "response": "종로의 봉인이 살아나면 네 눈은 안정될 것이니라. 하지만 망각귀의 뿌리는 팔도 곳곳에 남아 있지."},
            "C": {"role": "다음액션진행", "response": "글빛 五序를 알고 왔는가. 그럼 다섯 조각을 이 광장 위에 올려보거라. 단, 조각을 아무렇게나 올리면 기억은 다시 흩어질 것이다. 네가 지나온 순서대로 글빛을 놓아보거라."},
        },
        "mission": None,
        "quiz": None,  # 퀴즈 대신 5조각 순서 배치 퍼즐(final_order) — 실제 원형배치·드래그 UI는 앱 담당
        "objective": None,
        "final_order": FINAL_ORDER,
        "final_order_labels": ["먹빛", "온기", "붓끝", "손결", "처마빛"],
        "final_restore_dialogue": (
            "먹빛은 기록이 되고, 온기는 사람이 머문 흔적이 되며, 붓끝은 말을 남기고, 손의 결은 시간을 새기며, "
            "처마빛은 돌아갈 자리를 지키느니라.\n"
            "탐사자여, 네가 지나온 길이 하나의 글이 되었고, 그 글이 종로의 기억을 다시 깨웠도다.\n"
            "이제 종로의 글빛 기억석은 복원되었다. 망각귀의 봉인은 약하나마 다시 이어졌고, 잊혀 가던 도깨비들도 "
            "제 이름을 되찾았느니라."
        ),
        "endings": {"A": ending_a, "B": ending_b},
        "requires": [
            "fragment:종로_stone_1of5", "fragment:종로_stone_2of5", "fragment:종로_stone_3of5",
            "fragment:종로_stone_4of5", "fragment:종로_stone_5of5",
        ],
        "requires_mode": "hard",
        "grants": ["flag:종로_복원완료"],
        "clue": None,
        "success": ["place_verified", "combine_done"],
        "hint_ladder": {
            "H1": "이제껏 모은 다섯 조각을 도깨비에게 보이거라",
            "H2": "조각은 순서가 있다 — 글빛 五序를 떠올리거라",
            "H3": "먹빛 → 온기 → 붓끝 → 손결 → 처마빛, 지나온 길 그대로니라",
            "open_rule": ["fail1|idle60", "idle90", "button"],
        },
        "final_rewards_common": {
            "region_stone": {"name": "종로 글빛 기억석", "desc": "종로의 다섯 글빛 조각이 하나로 합쳐진 기억석"},
            "codex": "글빛 수호 도깨비 등록(최종노드 NPC 도감 등록)",
            "next_content": "팔도 기억 지도 첫 칸 해금(다음 지역 챕터 진입 가능)",
            "story": "망각귀 봉인 일부 회복(종로 지역 봉인이 복원됨)",
        },
        "garden_reward_common": {
            "item": "종로 글빛 기억석", "type": "챕터 핵심 오브제",
            "desc": "기억정원 중앙에 배치 가능한 종로 대표 기억석. 배치 시 푸른 글빛 이펙트가 발생함",
        },
        "codex_npc": "글빛 수호 도깨비",
        "codex_condition": "finale",
    }


def generate_jongno_script(region: str = "종로") -> dict[str, Any]:
    """종로 정답지(PDF §3) 고정 재생. region은 호환성 검증용(항상 "종로")."""
    if region != "종로":
        raise ValueError(f"jongno_script는 종로 전용. 받은 region={region}")

    quests = [
        build_quest_0_prologue(),
        build_quest_1_unhyeongung(),
        build_quest_2_ikseondong(),
        build_quest_3_insadong(),
        build_quest_4_gongye(),
        build_quest_5_bukchon(),
        build_quest_6_gwanghwamun_finale(),
    ]

    return {
        "scenario_id": "scn_종로_정답지",
        "title": "종로, 꺼져가는 글빛의 봉인",
        "region": "종로",
        "type": "jongno_fixed",
        "node_sequence": quests,
        "stone_total": 5,
        "anchor_node_id": "tour_unhyeongung",
        "is_public": False,
        "created_by": "system",
        "budget": 20000,
        "headcount": 1,
        "transport": "walk",
        "wishlist_content_ids": [],
        "is_branching": False,
        "route_tree": None,
        "play_time_estimate": "약 2시간",
        "theme": "글, 기록, 골목, 사람의 온기, 손의 기억",
    }
