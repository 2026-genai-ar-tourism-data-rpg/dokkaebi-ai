# ============================================================
# [v1] RedisWorkQueue 테스트 — put/get 직렬화 + SHUTDOWN 센티넬 + join
# pipeline: 공통 인프라 (테스트)
# 구현(요약): job 왕복(pickle)·SHUTDOWN identity 보존(마커 왕복)·task_done/join 로컬 카운팅,
#            3가지를 실제 redis 서버 없이(redis.asyncio.from_url 모킹) plain assert로 검증.
#            pytest 없이도 실행: `PYTHONPATH=. python tests/core/test_queue_redis.py`
# 구현일: 2026-08-12 | 작성: 정찬희
# ============================================================
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.queue import SHUTDOWN, RedisWorkQueue


def _fake_redis_client():
    """실제 Redis 대신 dict+list로 LPUSH/BRPOP을 흉내내는 최소 페이크."""
    store: list = []

    async def lpush(key, payload):
        store.insert(0, payload)

    async def brpop(key):
        while not store:  # 실제 BRPOP처럼 들어올 때까지 대기(테스트는 put이 먼저 끝난 뒤 호출)
            await asyncio.sleep(0)
        return (key, store.pop())

    client = MagicMock()
    client.lpush = AsyncMock(side_effect=lpush)
    client.brpop = AsyncMock(side_effect=brpop)
    return client


def test_put_get_roundtrips_job_via_pickle():
    """정상: 넣은 파이썬 객체(dict)가 pickle 왕복 후에도 동일하게 나온다."""
    with patch("redis.asyncio.from_url", return_value=_fake_redis_client()):
        q = RedisWorkQueue(url="redis://localhost:6379/0", key="test-queue")

        async def _run():
            await q.put({"job": "embed", "node_id": "tour_1"})
            return await q.get()

        job = asyncio.run(_run())

    assert job == {"job": "embed", "node_id": "tour_1"}


def test_shutdown_sentinel_identity_preserved_across_marker():
    """엣지: SHUTDOWN은 object()라 pickle identity가 깨지는데, 마커 왕복으로 `is SHUTDOWN`이 유지됨."""
    with patch("redis.asyncio.from_url", return_value=_fake_redis_client()):
        q = RedisWorkQueue(url="redis://localhost:6379/0", key="test-queue")

        async def _run():
            await q.put(SHUTDOWN)
            return await q.get()

        result = asyncio.run(_run())

    assert result is SHUTDOWN  # == 이 아니라 is — 워커의 `job is SHUTDOWN` 분기가 실제로 동작해야 함


def test_task_done_and_join_track_local_puts():
    """정상: put한 만큼 task_done 하면 join()이 즉시 풀린다(로컬 카운터)."""
    with patch("redis.asyncio.from_url", return_value=_fake_redis_client()):
        q = RedisWorkQueue(url="redis://localhost:6379/0", key="test-queue")

        async def _run():
            await q.put("a")
            await q.put("b")
            await q.get()
            q.task_done()
            await q.get()
            q.task_done()
            await asyncio.wait_for(q.join(), timeout=1.0)  # 안 풀리면 타임아웃으로 실패

        asyncio.run(_run())  # 예외(타임아웃) 없이 끝나면 통과


def _run_all() -> int:
    """pytest 없이 직접 실행하는 미니 러너. 실패가 있으면 종료코드 1."""
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL  {test.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    import sys

    sys.exit(_run_all())
