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
    search_min_score: float = 0.3       # 최소 유사도(이하 = 무관). 저신뢰 재검색 임계는 박준형 튜닝

    # --- 지역 인메모리 캐시 (존 서버 패턴) ---
    region_cache_max: int = 8           # 동시 상주 지역 수 (LRU)

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
