# ============================================================
# [v1] 설정(config) — 모든 매직넘버·동시성 수치의 단일 소스
# pipeline: 공통 인프라 (전 모듈이 참조)
# 구현(요약): 앱/LLM 동시성(세마포어)·재시도·백오프·지역캐시 설정값 + 싱글톤 로더
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수(.env, DOKKAEBI_*)로 주입되는 전역 설정. 매직넘버는 전부 여기로."""

    # --- 앱 ---
    app_name: str = "dokkaebi-ai"
    env: str = "local"
    log_level: str = "INFO"

    # --- LLM provider 선택 (교체 지점) ---
    #  mock              : 키 없이 구동(테스트)
    #  upstage | openai  : OpenAI 호환(chat/completions) — base_url/model만 바꾸면 호환끼리 교체
    #  (HyperCLOVA/Claude 등 비호환은 providers/ 에 파일 1개 추가)
    llm_provider: str = "mock"
    llm_base_url: str = "https://api.upstage.ai/v1"   # Upstage(Solar) 기본. OpenAI면 https://api.openai.com/v1
    llm_model: str = "solar-pro"                       # upstage: solar-pro / openai: gpt-4o-mini 등
    llm_api_key: str = ""
    llm_temperature: float = 0.7
    llm_max_tokens: int = 512

    # --- LLM 동시성/재시도 (API 호출부 안전: 세마포어 + 429 백오프) ---
    llm_semaphore: int = 8              # 동시 LLM 호출 상한 (세마포어 개수 — 여기서 조절)
    llm_max_retries: int = 5            # 429 등 재시도 횟수
    llm_backoff_base: float = 0.5       # 지수 백오프 base(초)
    llm_backoff_max: float = 20.0       # 백오프 상한(초)
    llm_timeout: float = 30.0           # 단일 호출 타임아웃(초)

    # --- 임베딩 provider 선택 (의미검색 기능 ②③ — 기획 11-10) ---
    #  mock              : 키 없이 구동(결정적 더미 벡터)
    #  upstage | openai  : OpenAI 호환(/embeddings) — base_url/model/key만 바꾸면 호환끼리 교체
    #  Tier 1: 지역 한정 인메모리 numpy 코사인. Vector DB 없음(발전방향).
    embed_provider: str = "mock"
    embed_base_url: str = "https://api.upstage.ai/v1"  # Upstage 기본. OpenAI면 https://api.openai.com/v1
    embed_model: str = "solar-embedding-1-large"        # upstage / openai: text-embedding-3-small 등
    embed_api_key: str = ""
    embed_dim: int = 1024               # 벡터 차원 (모델에 맞춰: solar=1024, openai-3-small=1536)

    # --- 임베딩 동시성/재시도 (배치 인덱싱 시 대량 호출 → 세마포어 + 429 백오프) ---
    embed_semaphore: int = 8            # 동시 임베딩 호출 상한 (여기서 조절)
    embed_max_retries: int = 5          # 429 등 재시도 횟수
    embed_backoff_base: float = 0.5     # 지수 백오프 base(초)
    embed_backoff_max: float = 20.0     # 백오프 상한(초)
    embed_timeout: float = 30.0         # 단일 호출 타임아웃(초)

    # --- 의미검색(retrieve 노드) 파라미터 (검색 알고리즘: 박준형) ---
    search_top_k: int = 5               # 코사인 top-k 후보 수
    search_min_score: float = 0.3       # 최소 유사도(이하 = 무관)
    search_low_confidence_threshold: float = 0.5  # 이 미만이면 쿼리 재작성 후 1회 재검색(튜닝 필요)
    search_rerank_lexical_weight: float = 0.3     # 재랭킹 블렌드: 코사인*(1-w) + 키워드overlap*w

    # --- TourAPI (국문관광정보 — 노드 데이터 원천) ---
    #  service_key 없으면 mock 종로 노드로 구동(거리순 로직 검증)
    #  ⚠️ 오퍼레이션 버전(KorService1/2)은 키 발급 후 Swagger로 확정
    #  ⚠️ 반드시 https — 평문 http는 응답 없이 타임아웃된다(2026-08 실측: http 25s 무응답 /
    #     https 0.17s 200). 장애로 오인하기 쉬우니 프로토콜을 바꾸지 말 것.
    tourapi_base_url: str = "https://apis.data.go.kr/B551011/KorService2"  # 노드 데이터(좌표·설명)
    tourapi_data_base_url: str = "https://apis.data.go.kr/B551011"         # 빅데이터 계열 루트(연관·집중률·중심·방문자수)
    tourapi_service_key: str = ""
    tourapi_mobile_os: str = "ETC"
    tourapi_mobile_app: str = "dokkaebi"
    tourapi_timeout: float = 10.0

    # --- OSM (키리스 실데이터 폴백 — TourAPI 키 없을 때 POI·검색 원천) ---
    #  Overpass(반경 POI)·Nominatim(키워드 검색) 공개 인스턴스. 상용 트래픽 금지·
    #  User-Agent 필수(정책). 캐시로 호출 최소화 — Nominatim은 1req/s 제한.
    # ⚠️ **전역 커버리지 미러만 넣을 것.** overpass.osm.ch는 0.9s로 가장 빨라 1순위로
    #   뒀다가 걸렸다 — 스위스 전용 DB라 한국 쿼리에 200 + 빈 결과를 준다(실측:
    #   한국 0건 / 취리히 20건). 200이라 페일오버도 안 걸려 조용히 빈 코스가 된다.
    #   osm.py가 "빈 결과도 실패로 간주"해 다음 미러로 넘기지만, 애초에 넣지 말 것.
    # ⚠️ 한때 미러가 동시에 전부 죽어 시나리오 생성이 500으로 막힌 적이 있다
    #   → 전부 실패해도 Nominatim 폴백(osm.py)이 받아 코스는 만들어진다.
    osm_overpass_urls: str = (
        "https://maps.mail.ru/osm/tools/overpass/api/interpreter,"
        "https://overpass-api.de/api/interpreter,"
        "https://overpass.kumi.systems/api/interpreter"
    )
    osm_nominatim_url: str = "https://nominatim.openstreetmap.org/search"
    # 미러당 타임아웃 — 짧게 잡고 빨리 다음 미러로(전 미러 대기가 사용자 체감 지연).
    osm_timeout: float = 8.0
    # POI는 거의 정적 → 길게. 미러가 다 죽어도 캐시가 있으면 그 좌표는 계속 돈다.
    osm_cache_ttl_s: int = 86400
    osm_user_agent: str = "dokkaebi-ai/0.1 (dev; contact: team)"

    # --- 분기 대화 (찐 RPG, 기획 8-D) ---
    max_dialogue_turns: int = 3          # 노드당 대화 깊이 상한(초과 시 의뢰 수령으로 수렴)
    dialogue_history_turns: int = 6      # 프롬프트에 넣을 최근 대화 줄 수(글자수로 자르면 문장이 깨짐)

    # --- 프롬프트 버전 (캐시 키에 박히는 값) ---
    #  ⚠️ 프롬프트·템플릿을 고치면 **반드시** 올릴 것. 캐시 키에 이 값이 없으면
    #     대사는 cache_ttl_s(1일), 페르소나는 7일 동안 옛 출력이 계속 나간다
    #     ("고쳤는데 왜 그대로냐"의 원인). 올린 직후 첫 요청은 전 노드 재생성이라
    #     LLM 호출이 몰린다 → 시연 직전에 올리지 말고 미리 한 번 데워 둘 것.
    prompt_version: str = "v2"

    # --- 시나리오 생성 (거리순 v0) ---
    scenario_content_type_id: int = 12   # 12=관광지 (식당39 등은 나중)
    scenario_node_count: int = 5         # 기억석 조각 수 = 방문 장소 수
    scenario_default_radius_m: int = 2000
    scenario_radius_walk_m: int = 2000   # 이동수단=도보 기본 반경
    scenario_radius_car_m: int = 8000    # 이동수단=차 기본 반경
    # 노드 선택 hook 스위치(build_route) — 0=off면 기존 거리순 동작 그대로
    scenario_lowtraffic_anchors: int = 0  # 비인기 앵커(샛길) 강제포함 수 — 박준형 EDA 후 >0
    scenario_food_per_route: int = 0      # 경로당 삽입할 카페/식당 수 — 정찬희 실데이터 후 >0

    # --- 식음 삽입/예산 게이팅 (food.py — 박준형) ---
    food_min_meal_target_krw: int = 4000  # 식사 슬롯 성립 최소 1인 예산 (정책값) — 미만이면 카페 다운그레이드
    food_min_cafe_target_krw: int = 2500  # 카페 슬롯 성립 최소 1인 예산 (정책값) — 미만이면 식음 0개 폴백
    food_search_radius_m: int = 1000       # 삽입 지점(구간 중간) 주변 후보 검색 반경
    food_fetch_rows: int = 30             # TourAPI 39 후보 fetch 개수
    # 1인 예산 → 목표 가격대 밴드(₩~₩₩₩₩) 경계 — ⚠️ "정책값"(데이터 주장 아님):
    #  구글은 priceLevel의 원화 기준을 공개하지 않으므로 이 경계는 팀이 정하는 규칙
    #  (trigger_radius처럼). 데모 돌려보며 팀이 조정.
    food_band1_max_krw: int = 10000       # 미만 = ₩
    food_band2_max_krw: int = 30000       # 미만 = ₩₩
    food_band3_max_krw: int = 60000       # 미만 = ₩₩₩, 이상 = ₩₩₩₩
    food_unknown_band_score: float | None = None  # None = 미상 후보 배제

    # --- Google Places priceLevel (google_places.py — 박준형) ---
    #  ⚠️ 채택 조건부: scripts/measure_price_coverage.py 종로 보유율 실측 후 확정 (HANDOFF §6)
    #  키 없으면 가격대 미상 처리(호출 0). billing 연결 + 콘솔 일일 상한 설정은 사람이 할 것.
    google_maps_api_key: str = "" # 필드 선언
    google_places_timeout: float = 10.0
    google_places_semaphore: int = 5      # 동시 priceLevel 조회 상한
    google_price_cache_ttl_s: int = 604800  # 7일 — 업소 가격대는 거의 안 바뀜(무료쿼터 절약)

    # --- 비인기지역 앵커 선택 (TourAPI BigData 기반) ---
    # MVP는 종로 고정. 지역 확장 시 density_region_code_map에 매핑 추가.
    density_default_region: str = "종로"
    density_region_code_map: dict[str, dict[str, str]] = {
        "종로": {"areaCd": "11", "signguCd": "11110"}
    }
    # hubRank는 관광지+숙박이 섞인 전역 순위라 그대로 쓰면 top_n이 호텔에 잠식됨.
    # → density.py에서 allowed_hub_category로 거른 뒤 카테고리 내 상대순위로 재계산해서 비교.
    density_hub_popular_top_n: int = 20       # (카테고리 내 상대)순위 <= N이면 중심 관광지로 보고 제외
    density_allowed_hub_category: str = "관광지"
    # 종로 실측(2026-07-13, 113개 장소 avg_cnctrRate 분포) p75. 근처 후보가 전부 혼잡해도
    # 절대적으로 이 값을 넘으면 '비인기'로 인정하지 않음(상대순위만으로는 진짜 혼잡지도 뽑힐 수 있어서).
    # median(63.1)은 최번화가(안국역 인근) 기준점에서 항상 0개가 나와 p75로 완화함.
    density_lowtraffic_max_avg_rate: float = 70.9

    # BigData bulk fetch: numOfRows는 페이지당 row 수. 종로 실측 3390 rows → 1000이면 약 4페이지.
    density_cnctr_num_of_rows: int = 1000
    density_cnctr_max_pages: int = 20
    density_hub_num_of_rows: int = 100
    density_hub_max_pages: int = 20
    density_hub_base_months_ago: int = 3

    # Selection / fallback
    density_candidate_limit: int = 20         # API/매칭 평가 대상 후보 수
    density_targeted_fallback_limit: int = 3  # 벌크 매칭 실패 시 개별 tAtsNm 조회 허용 수
    density_targeted_num_of_rows: int = 30    # 개별 tAtsNm 조회 page size

    # Cache
    density_bigdata_cache_ttl_s: int = 21600  # 6시간

    # --- 캐시 (대사·노드 상세) ---
    #  memory: 인프로세스(키 없이 구동) / redis: 공유 캐시(compose·배포)
    cache_backend: str = "memory"
    cache_ttl_s: int = 86400            # 대사 캐시 TTL(초) — 기본 1일
    tourapi_cache_ttl_s: int = 604800   # 노드 상세(overview) 캐시 TTL — 기본 7일(거의 정적)
    # memory 백엔드 엔트리 상한 — 만료됐지만 재조회되지 않는 키가 쌓이는 것을 막는다.
    cache_max_entries: int = 10000      # 초과 시 만료분 정리 → 오래된 순 제거

    # --- 지역 인메모리 캐시 (존 서버 패턴) ---
    region_cache_max: int = 8           # 동시 상주 지역 수 (LRU)
    # warm()이 병합이라 지역 워킹셋이 계속 누적된다 → 지역당 노드 수도 LRU로 상한.
    # 노드당 overview 수 KB 기준, 8지역 × 500노드면 수십 MB 수준.
    region_cache_nodes_max: int = 500   # 지역당 상주 노드 수 (LRU)

    # --- 작업 큐 / 워커 (고처리량 배치) ---
    worker_count: int = 4               # 작업 큐 병렬 소비 워커 수
    queue_maxsize: int = 0              # 큐 상한 (0=무제한, >0이면 백프레셔)

    # --- 외부 서비스 (compose 네트워크에선 서비스명으로 접속) ---
    database_url: str = "postgresql://dokkaebi:dokkaebi@localhost:5432/dokkaebi"
    redis_url: str = "redis://localhost:6379"

    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="DOKKAEBI_", extra="ignore"
    )


@lru_cache
def get_settings() -> Settings:
    """설정 싱글톤 반환 — 프로세스당 1회만 .env 로드."""
    return Settings()