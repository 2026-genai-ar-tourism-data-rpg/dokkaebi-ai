# ============================================================
# [v1] 캐시 추상화 — 대사·노드 상세 캐시 (memory / redis 교체)
# pipeline: 공통 인프라 (persist-on-touch · 대사 캐시 백엔드)
# 구현(요약): CacheBackend 추상 + MemoryCache(인프로세스 TTL)·RedisCache(공유).
#            config.cache_backend로 선택. Redis 오류 시 graceful 미스(앱 안 죽음).
#            provider 교체는 get_cache 한 곳에서만(LLM 패턴과 동일).
# 구현일: 2026-06-18 | 작성: kys (cache-wire/kys/v1)
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
    """인프로세스 TTL 캐시. Redis 없이 구동(로컬·테스트). 휘발성·인스턴스별."""

    def __init__(self) -> None:
        self._store: dict[str, tuple[str, float | None]] = {}  # key -> (value, expire_at)

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
        exp = time.monotonic() + ttl_s if ttl_s else None
        self._store[key] = (value, exp)


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
