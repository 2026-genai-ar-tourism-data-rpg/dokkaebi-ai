# ============================================================
# [v1] 캐시 추상화 — 대사·노드 상세 캐시 (memory / redis 교체)
# pipeline: 공통 인프라 (persist-on-touch · 대사 캐시 백엔드)
# 구현(요약): CacheBackend 추상 + MemoryCache(인프로세스 TTL)·RedisCache(공유).
#            config.cache_backend로 선택. Redis 오류 시 graceful 미스(앱 안 죽음).
#            provider 교체는 get_cache 한 곳에서만(LLM 패턴과 동일).
# 구현일: 2026-06-18 | 작성: kys (cache-wire/kys/v1)
# ------------------------------------------------------------
# [v2] MemoryCache 무한 증식 차단 — 만료 항목 정리 + 엔트리 수 상한(LRU-ish).
# 구현(요약): 기존 MemoryCache는 만료 항목을 '조회할 때만' 지우고 크기 상한이 없었다.
#            다시 조회되지 않는 키(대사 1일·노드상세 7일·가격 7일)가 만료 후에도 계속
#            남아 장기 구동 프로세스에서 서서히 샜다. set 시 상한 초과면 만료분을 먼저
#            비우고, 그래도 넘치면 오래 들어온 순으로 버린다(dict 삽입순).
# 구현일: 2026-08-12 | 작성: pjh (ai-logic-fix/pjh/v2)
# ============================================================
import time
from abc import ABC, abstractmethod

from app.config import get_settings
from app.core.logger import get_logger

logger = get_logger(__name__)


class CacheBackend(ABC):
    """문자열 키-값 캐시 추상 인터페이스(TTL 지원)."""

    @abstractmethod
    async def get(self, key: str) -> str | None: ...

    @abstractmethod
    async def set(self, key: str, value: str, ttl_s: int) -> None: ...


class MemoryCache(CacheBackend):
    """인프로세스 TTL 캐시. Redis 없이 구동(로컬·테스트). 휘발성·인스턴스별.

    엔트리 수를 max_entries로 제한한다 — 만료됐지만 아무도 다시 조회하지 않는 키가
    쌓이면 장기 구동 프로세스에서 메모리가 계속 늘어나기 때문.
    """

    def __init__(self, max_entries: int | None = None) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}  # key -> (value, expire_at)
        self._max = max_entries if max_entries is not None else get_settings().cache_max_entries

    async def get(self, key: str) -> str | None:
        v = self._store.get(key)
        if not v:
            return None
        value, exp = v
        if exp is not None and exp < time.monotonic():  # 만료
            self._store.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        exp = time.monotonic() + ttl_s if ttl_s else None   # ttl_s=0 → 만료 없음(영구)
        self._store[key] = (value, exp)
        if len(self._store) > self._max:
            self._evict()

    def _evict(self) -> None:
        """상한 초과 시 ① 만료분 정리 → ② 그래도 넘치면 오래 들어온 순으로 버린다."""
        now = time.monotonic()
        for key in [k for k, (_, exp) in self._store.items() if exp is not None and exp < now]:
            self._store.pop(key, None)

        overflow = len(self._store) - self._max
        if overflow > 0:
            # dict는 삽입 순서를 유지 → 앞쪽이 가장 오래된 항목
            for key in list(self._store)[:overflow]:
                self._store.pop(key, None)
            logger.info("메모리 캐시 상한(%d) 초과 → 오래된 항목 %d개 제거", self._max, overflow)


class RedisCache(CacheBackend):
    """Redis 공유 캐시(인스턴스 간 공유). 연결 오류 시 캐시 미스로 degrade(앱 유지)."""

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis
        self._r = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | None:
        try:
            return await self._r.get(key)
        except Exception as e:  # 연결 끊김 등 → 미스로 처리
            logger.warning("Redis get 실패(미스 처리): %s", e)
            return None

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        try:
            await self._r.set(key, value, ex=ttl_s or None)
        except Exception as e:
            logger.warning("Redis set 실패(무시): %s", e)


_cache: CacheBackend | None = None


def get_cache() -> CacheBackend:
    """캐시 싱글톤. config.cache_backend로 backend 선택(memory/redis)."""
    global _cache
    if _cache is None:
        s = get_settings()
        if s.cache_backend == "redis":
            try:
                _cache = RedisCache(s.redis_url)
                logger.info("캐시 backend = redis (%s)", s.redis_url)
            except Exception as e:  # redis-py 미설치 등 → 메모리 폴백
                logger.warning("Redis 캐시 초기화 실패 → memory 폴백: %s", e)
                _cache = MemoryCache()
        else:
            _cache = MemoryCache()
            logger.info("캐시 backend = memory (인프로세스)")
    return _cache
