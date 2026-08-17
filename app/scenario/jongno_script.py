# ============================================================
# [v1] 종로 고정 스크립트 — MVP 정답지 재생
# scenario: 종로 지역 (「종로, 잊혀진 글씨의 비밀」)
# 구현(요약): PDF 기획서 6개 노드를 완성된 quest dict로 하드코딩.
#            generate_scenario에서 region=="종로" 분기로 동적 파이프라인 우회.
#            각 노드는 validate_app_contract 통과, 앱 호환 완전 자립.
# 구현일: 2026-08-18 | 작성: 정찬희
# ============================================================
from typing import Any


# --- 노드 좌표(실제 공개 데이터) ---
NODES_GEO = {
    "tour_unhyeongung": {"lat": 37.5745, "lng": 126.9858},      # 운현궁
    "tour_ikseondong": {"lat": 37.5740, "lng": 126.9905},       # 익선동 한옥카페
    "tour_insadong": {"lat": 37.5740, "lng": 126.9856},         # 인사동
    "tour_gongye": {"lat": 37.5765, "lng": 126.9800},           # 서울공예박물관
    "tour_bukchon": {"lat": 37.5826, "lng": 126.9850},          # 북촌한옥마을
    "tour_gwanghwamun": {"lat": 37.5728, "lng": 126.9766},      # 광화문광장
}

NODES_NAME = {
    "tour_unhyeongung": "운현궁",
    "tour_ikseondong": "익선동 한옥카페",
    "tour_insadong": "인사동",
    "tour_gongye": "서울공예박물관",
    "tour_bukchon": "북촌한옥마을",
    "tour_gwanghwamun": "광화문광장",
}


def _choice(label: str, text: str, flags: list[str] | None = None, affinity: int = 0,
            reward_mod: dict[str, Any] | None = None) -> dict[str, Any]:
    """선택지 빌더."""
    c = {"id": label, "text": text}
    if flags:
        c["flags"] = flags
    if affinity:
        c["affinity"] = affinity
    if reward_mod:
        c["reward_mod"] = reward_mod
    return c


def build_quest_1_unhyeongung() -> dict[str, Any]:
    """1. 운현궁 — 먹 도깨비 (모티프: 붓·먹)."""
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
        "fragment_id": "종로_stone_1of3",
        "is_finale": False,
        "npc": {
            "name": "먹 도깨비",
            "archetype": "guardian",
            "motif": "붓, 먹",
            "persona": "옛 글을 지키는 과묵하고 위엄 있는 도깨비. 세종의 글씨를 찾기 위한 여정을 인도한다.",
        },
        "npc_dialogue": "허허, 운현궁에 발을 들였구나. 흥선대원군이 살던 이 사저에… 어느 날 세종 임금의 글씨 한 조각이 먹물 속으로 숨어버렸느니라. 자네, 글을 아끼는 자인가?",
        "motivation": ["M1", "M7"],
        "strategy": ["S4_PHOTO_TRAIL", "S3_RIDDLE_UNLOCK"],
        "actions": [
            {"a": "goto", "place": "운현궁"},
            {
                "a": "listen",
                "slot": "intro+choices",
                "choices": [
                    _choice("A", "세종대왕의 글씨라니, 무슨 일이오?", flags=["호기심"], affinity=1),
                    _choice("B", "보상은 무엇이오?", reward_mod={"coupon": 100}),
                    _choice("C", "그냥 빨리 찾겠소."),
                ],
            },
            {"a": "capture", "targets": ["대문", "마당", "전통건물 외관"]},
            {"a": "follow", "object": "먹물 발자국", "steps": 3},
            {"a": "tap", "target": "글씨파편", "count": [0, 1]},
            {"a": "report", "npc": "먹 도깨비"},
        ],
        "mission": {
            "type": "photo_trail",
            "order": "PHOTO_TRAIL",
            "hints": [
                {"step": 1, "text": "발자국은 해 지는 쪽으로 번졌느니"},
                {"step": 2, "text": "이로당 처마 아래니라"},
                {"step": 3, "text": "처마 그늘 왼편, 세 번째 서까래"},
            ],
        },
        "quiz": {
            "question": "운현궁은 누구의 집이었더냐?",
            "options": ["세종대왕", "흥선대원군", "정조"],
            "answer_idx": 1,
            "correct": {"exp": 30, "coupon": 200},
            "hints": {
                "H1": "발자국은 해 지는 쪽으로 번졌느니",
                "H2": "이로당 처마 아래니라",
                "H3": "처마 그늘 왼편, 세 번째 서까래",
                "open_rule": ["fail1|idle60", "idle90", "button"],
            },
        },
        "objective": {
            "order": "PHOTO_TRAIL",
            "hints": [
                "발자국은 해 지는 쪽으로 번졌느니",
                "이로당 처마 아래니라",
                "처마 그늘 왼편, 세 번째 서까래",
            ],
        },
        "requires": [],
        "requires_mode": "none",
        "grants": ["fragment:종로_stone_1of3", "clue:申時"],
        "clue": "申時",
        "success": ["place_verified", "quiz_correct", "photo_done", "follow:먹물 발자국>=3", "tap:글씨파편>=1"],
        "hint_ladder": {
            "H1": "발자국은 해 지는 쪽으로 번졌느니",
            "H2": "이로당 처마 아래니라",
            "H3": "처마 그늘 왼편, 세 번째 서까래",
            "open_rule": ["fail1|idle60", "idle90", "button"],
        },
    }


def build_quest_2_ikseondong() -> dict[str, Any]:
    """2. 익선동 한옥카페 — 한옥 도깨비 (모티프: 기와·차)."""
    return {
        "order": 2,
        "node_id": "tour_ikseondong",
        "name": "익선동 한옥카페",
        "kind": "spot",
        "map_x": NODES_GEO["tour_ikseondong"]["lng"],
        "map_y": NODES_GEO["tour_ikseondong"]["lat"],
        "dist_m": 1.0,
        "density_tier": None,
        "source": "jongno_script",
        "out_of_radius": False,
        "trigger_radius_m": 100,
        "stone_no": 2,
        "fragment_id": "종로_stone_2of3",
        "is_finale": False,
        "npc": {
            "name": "한옥 도깨비",
            "archetype": "guardian",
            "motif": "기와, 차",
            "persona": "익선동의 오래된 한옥 골목을 지키는 온화한 도깨비. 차의 향기 속에 숨겨진 비밀을 알고 있다.",
        },
        "npc_dialogue": "허허, 운현궁에서 申時 단서를 얻어 왔구나! 그 시각, 이 골목 가마솥에 글씨 하나가 떨어졌지. 차 한 잔 시키고 천천히 둘러보거라.",
        "motivation": ["M6", "M4"],
        "strategy": ["S7_PATRONIZE", "S3_RIDDLE_UNLOCK"],
        "actions": [
            {"a": "goto", "place": "익선동 한옥카페"},
            {
                "a": "listen",
                "slot": "intro+choices",
                "choices": [
                    _choice("A", "이 골목은 왜 한옥이 많소?", flags=["한옥통"], affinity=1),
                    _choice("B", "추천 메뉴가 있소?"),
                ],
            },
            {"a": "purchase", "menu": "익선동 한 상", "optional": True, "verification": "receipt"},
            {"a": "answer", "quiz": {"answer_idx": 1, "correct": {"exp": 20, "coupon": 300}}},
            {"a": "tap", "target": "글씨파편", "count": [0, 1]},
            {"a": "report", "npc": "한옥 도깨비"},
        ],
        "mission": {
            "type": "riddle_unlock",
            "order": "RIDDLE",
            "hints": [
                {"step": 1, "text": "이 골목 이름에 뜻이 숨어 있느니"},
                {"step": 2, "text": "'더한다'는 뜻의 한자를 떠올려 보거라"},
                {"step": 3, "text": "날개도 물도 아니다, 무언가를 보태는 글자니라"},
            ],
        },
        "quiz": {
            "question": "익선동의 '익'은 무엇을 뜻하겠느냐?",
            "options": ["날개", "더할 익(益)", "물"],
            "answer_idx": 1,
            "correct": {"exp": 20, "coupon": 300},
            "hints": {
                "H1": "이 골목 이름에 뜻이 숨어 있느니",
                "H2": "'더한다'는 뜻의 한자를 떠올려 보거라",
                "H3": "날개도 물도 아니다, 무언가를 보태는 글자니라",
                "open_rule": ["fail1|idle60", "idle90", "button"],
            },
        },
        "objective": {
            "order": "RIDDLE",
            "hints": [
                "이 골목 이름에 뜻이 숨어 있느니",
                "'더한다'는 뜻의 한자를 떠올려 보거라",
                "날개도 물도 아니다, 무언가를 보태는 글자니라",
            ],
        },
        "requires": ["clue:申時"],
        "requires_mode": "soft",
        "grants": ["fragment:종로_stone_2of3", "clue:ㄱ"],
        "clue": "ㄱ",
        "success": ["place_verified", "one_of:purchase_verified|tap_done", "quiz_correct", "tap:글씨파편>=1"],
        "hint_ladder": {
            "H1": "이 골목 이름에 뜻이 숨어 있느니",
            "H2": "'더한다'는 뜻의 한자를 떠올려 보거라",
            "H3": "날개도 물도 아니다, 무언가를 보태는 글자니라",
            "open_rule": ["fail1|idle60", "idle90", "button"],
        },
    }


def build_quest_3_insadong() -> dict[str, Any]:
    """3. 인사동 — 붓장수 도깨비 (모티프: 붓·글씨)."""
    return {
        "order": 3,
        "node_id": "tour_insadong",
        "name": "인사동",
        "kind": "spot",
        "map_x": NODES_GEO["tour_insadong"]["lng"],
        "map_y": NODES_GEO["tour_insadong"]["lat"],
        "dist_m": 1.0,
        "density_tier": None,
        "source": "jongno_script",
        "out_of_radius": False,
        "trigger_radius_m": 100,
        "stone_no": 3,
        "fragment_id": "종로_stone_3of3",
        "is_finale": False,
        "npc": {
            "name": "붓장수 도깨비",
            "archetype": "guardian",
            "motif": "붓, 글씨",
            "persona": "인사동 거리의 전통 간판과 글씨를 지키는 도깨비. 한글의 조합 원리를 알고 있다.",
        },
        "npc_dialogue": "글씨엔 자음과 모음이 있느니. 자네 'ㄱ'은 얻었으나 'ㅏ'가 없구나. 저 전통 간판을 화면에 담아 보거라 — 옛 글씨가 깨어날지니.",
        "motivation": ["M8", "M7"],
        "strategy": ["S5_PHOTO_PROOF", "S3_RIDDLE_UNLOCK"],
        "actions": [
            {"a": "goto", "place": "인사동"},
            {
                "a": "listen",
                "slot": "intro+choices",
                "choices": [
                    _choice("A", "이 간판들은 다 무슨 뜻이오?", flags=["호기심"], affinity=1),
                    _choice("B", "빨리 찾아보겠소."),
                ],
            },
            {"a": "capture", "targets": ["전통 간판", "먹글씨"]},
            {"a": "answer", "quiz": {"answer_idx": 0, "correct": {"exp": 30, "coupon": 200}}},
            {"a": "tap", "target": "글씨파편", "count": [0, 1]},
            {"a": "report", "npc": "붓장수 도깨비"},
        ],
        "mission": {
            "type": "photo_proof",
            "order": "PHOTO_PROOF",
            "hints": [
                {"step": 1, "text": "간판 위 글씨를 눈여겨보거라"},
                {"step": 2, "text": "'ㄱ'에 이을 소리가 저 현판 어딘가에 있느니라"},
                {"step": 3, "text": "제일 큰 간판을 화면 안에 크게 담아 보거라"},
            ],
        },
        "quiz": {
            "question": "'ㄱ'과 'ㅏ'를 합치면?",
            "options": ["개", "가", "그"],
            "answer_idx": 1,
            "correct": {"exp": 30, "coupon": 200},
            "hints": {
                "H1": "간판 위 글씨를 눈여겨보거라",
                "H2": "'ㄱ'에 이을 소리가 저 현판 어딘가에 있느니라",
                "H3": "제일 큰 간판을 화면 안에 크게 담아 보거라",
                "open_rule": ["fail1|idle60", "idle90", "button"],
            },
        },
        "objective": {
            "order": "PHOTO_PROOF",
            "hints": [
                "간판 위 글씨를 눈여겨보거라",
                "'ㄱ'에 이을 소리가 저 현판 어딘가에 있느니라",
                "제일 큰 간판을 화면 안에 크게 담아 보거라",
            ],
        },
        "requires": ["clue:ㄱ"],
        "requires_mode": "soft",
        "grants": ["fragment:종로_stone_3of3", "clue:ㅏ"],
        "clue": "ㅏ",
        "success": ["place_verified", "photo_done", "quiz_correct", "tap:글씨파편>=1"],
        "hint_ladder": {
            "H1": "간판 위 글씨를 눈여겨보거라",
            "H2": "'ㄱ'에 이을 소리가 저 현판 어딘가에 있느니라",
            "H3": "제일 큰 간판을 화면 안에 크게 담아 보거라",
            "open_rule": ["fail1|idle60", "idle90", "button"],
        },
    }


def build_quest_4_gwanghwamun_finale() -> dict[str, Any]:
    """4. 광화문 광장 (피날레) — 세종대왕 (M3+S6 조합)."""
    return {
        "order": 4,
        "node_id": "tour_gwanghwamun",
        "name": "광화문광장",
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
            "name": "세종대왕",
            "archetype": "historical_figure",
            "motif": "백성, 한글",
            "persona": "한글을 만든 위대한 왕. 백성의 글씨를 복원하려는 자를 인정하고 축복한다.",
        },
        "npc_dialogue": "그대가 흩어진 글씨를 모아 왔는가. 백성이 쉬이 익히라 만든 글이거늘, 잊혀선 아니 되네. 마지막 조각은… 그대 마음에 있네.",
        "motivation": ["M3"],
        "strategy": ["S6_ACCUMULATE"],
        "actions": [
            {"a": "goto", "place": "광화문광장"},
            {
                "a": "listen",
                "slot": "intro+ending_choice",
                "choices": [
                    _choice("A", "백성을 위한 글이었군요.", affinity=3, reward_mod={"relic": "집현전 붓"}),
                    _choice("B", "보상부터 주시죠."),
                ],
            },
            {"a": "combine", "items": ["fragment:종로_stone_1of3", "fragment:종로_stone_2of3", "fragment:종로_stone_3of3"]},
            {"a": "report", "npc": "세종대왕"},
        ],
        "mission": None,
        "quiz": None,
        "objective": None,
        "requires": ["fragment:종로_stone_1of3", "fragment:종로_stone_2of3", "fragment:종로_stone_3of3"],
        "requires_mode": "hard",
        "grants": ["flag:종로_복원완료"],
        "clue": None,
        "success": ["place_verified", "combine_done"],
        "hint_ladder": {
            "H1": "이제껏 모은 조각을 도깨비에게 보이거라",
            "H2": "세종대왕이 묻거든 마음에 있는 답을 하거라",
            "H3": "정답은 없다 — 어느 쪽을 골라도 조각은 하나로 모이느니라",
            "open_rule": ["fail1|idle60", "idle90", "button"],
        },
    }


def build_quest_5_yisunsin_side() -> dict[str, Any]:
    """5. 광화문 이순신 장군 (Floating Module — 사이드 퀘스트)."""
    return {
        "order": 4,  # 광화문 도착 시 함께 트리거되지만 본선은 아님
        "node_id": "side_yisunsin",
        "name": "이순신 장군상",
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
        "is_finale": False,
        "npc": {
            "name": "이순신 장군",
            "archetype": "historical_figure",
            "motif": "전술, 거북선",
            "persona": "해전의 승리로 나라를 지킨 장군. 과묵하고 결연한 말투로 진법의 지혜를 전한다.",
        },
        "npc_dialogue": "예까지 왔는가. 저 배의 위용을 담아보게. 그 뒤에 내 진법의 뜻을 묻겠네.",
        "motivation": ["M3", "M9"],
        "strategy": ["S5_PHOTO_PROOF", "S3_RIDDLE_UNLOCK"],
        "actions": [
            {"a": "goto", "place": "광화문광장"},
            {
                "a": "listen",
                "slot": "intro+choices",
                "choices": [
                    _choice("A", "장군의 활약이 궁금하오.", flags=["호기심"], affinity=1),
                    _choice("B", "바로 살펴보겠소."),
                ],
            },
            {"a": "capture", "targets": ["거북선 동상"]},
            {"a": "answer", "quiz": {"answer_idx": 1, "correct": {"exp": 20}}},
            {"a": "report", "npc": "이순신 장군"},
        ],
        "mission": {
            "type": "photo_proof",
            "order": "PHOTO_PROOF",
            "hints": [
                {"step": 1, "text": "새가 날아오르는 모습을 떠올려 보거라"},
                {"step": 2, "text": "이순신 장군이 짠 진법은 새의 날개를 닮았다 하지"},
                {"step": 3, "text": "양쪽으로 넓게 펼친 날개, 그 모양이 진법이었느니라"},
            ],
        },
        "quiz": {
            "question": "학익진은 무슨 모양인가?",
            "options": ["일자진형", "학이 날개 편 모양", "원형진"],
            "answer_idx": 1,
            "correct": {"exp": 20},
            "hints": {
                "H1": "새가 날아오르는 모습을 떠올려 보거라",
                "H2": "이순신 장군이 짠 진법은 새의 날개를 닮았다 하지",
                "H3": "양쪽으로 넓게 펼친 날개, 그 모양이 진법이었느니라",
                "open_rule": ["fail1|idle60", "idle90", "button"],
            },
        },
        "objective": {
            "order": "PHOTO_PROOF",
            "hints": [
                "새가 날아오르는 모습을 떠올려 보거라",
                "이순신 장군이 짠 진법은 새의 날개를 닮았다 하지",
                "양쪽으로 넓게 펼친 날개, 그 모양이 진법이었느니라",
            ],
        },
        "requires": [],
        "requires_mode": "none",
        "grants": ["relic:충무공의 나침반"],
        "clue": None,
        "success": ["place_verified", "photo_done", "quiz_correct"],
        "hint_ladder": {
            "H1": "새가 날아오르는 모습을 떠올려 보거라",
            "H2": "이순신 장군이 짠 진법은 새의 날개를 닮았다 하지",
            "H3": "양쪽으로 넓게 펼친 날개, 그 모양이 진법이었느니라",
            "open_rule": ["fail1|idle60", "idle90", "button"],
        },
    }


def generate_jongno_script(region: str = "종로") -> dict[str, Any]:
    """종로 정답지 시나리오 완성본 반환.

    region은 호환성 검증용(항상 "종로").
    """
    if region != "종로":
        raise ValueError(f"jongno_script는 종로 전용. 받은 region={region}")

    quests = [
        build_quest_1_unhyeongung(),
        build_quest_2_ikseondong(),
        build_quest_3_insadong(),
        build_quest_4_gwanghwamun_finale(),
        build_quest_5_yisunsin_side(),
    ]

    return {
        "scenario_id": "scn_종로_정답지",
        "title": "종로, 잊혀진 글씨의 비밀",
        "region": "종로",
        "type": "jongno_fixed",
        "node_sequence": quests,
        "stone_total": 3,
        "anchor_node_id": "tour_unhyeongung",
        "is_public": False,
        "created_by": "system",
        "budget": 20000,
        "headcount": 1,
        "transport": "walk",
        "wishlist_content_ids": [],
        "is_branching": False,
        "route_tree": None,
    }
