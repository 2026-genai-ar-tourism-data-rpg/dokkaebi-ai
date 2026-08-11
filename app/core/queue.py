# ============================================================
# [v1] 작업 큐 인터페이스 + 워커 풀
# pipeline: 공통 인프라 (고처리량 배치: 임베딩·시나리오 사전생성·수집)
# 구현(요약): WorkQueue 추상 인터페이스 + InMemoryWorkQueue(asyncio) + RedisWorkQueue +
#            run_workers(N개 워커 병렬 소비) + process_batch(원샷 배치 헬퍼).
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# 수정일: 2026-08-12 | RedisWorkQueue 구현: 정찬희 (SqsWorkQueue는 미착수 — 근거 없음, 최종 보고 참조)
# ============================================================
import asyncio
import pickle
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Sequence

from app.core.logger import get_logger

logger = get_logger(__name__)

# 워커 종료 신호용 센티넬 (큐에 넣으면 워커가 빠져나감)
SHUTDOWN = object()


class WorkQueue(ABC):
    """작업 큐 추상 인터페이스.

    구현체 교체로 인프로세스 ↔ 외부 큐(Redis) 전환:
      - InMemoryWorkQueue : 단일 프로세스·휘발성 (baseline)
      - RedisWorkQueue    : 크로스 프로세스·내구성
    핫패스 동기 호출의 동시성 제한은 큐가 아니라 LLMClient 세마포어가 담당(역할 분리).
    """

    @abstractmethod
    async def put(self, job: Any) -> None:
        """작업 1건 적재."""

    @abstractmethod
    async def get(self) -> Any:
        """작업 1건 꺼냄(없으면 대기)."""

    @abstractmethod
    def task_done(self) -> None:
        """1건 처리 완료 표시(join 용)."""

    @abstractmethod
    async def join(self) -> None:
        """모든 적재 작업이 처리 완료될 때까지 대기."""


class InMemoryWorkQueue(WorkQueue):
    """asyncio.Queue 기반 인프로세스 작업 큐 (baseline). 단일 프로세스·휘발성."""

    def __init__(self, maxsize: int = 0) -> None:
        # maxsize>0 이면 큐가 차면 put이 대기 → 백프레셔
        self._q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)

    async def put(self, job: Any) -> None:
        """작업 적재(큐 가득 차면 대기)."""
        await self._q.put(job)

    async def get(self) -> Any:
        """작업 1건 꺼냄."""
        return await self._q.get()

    def task_done(self) -> None:
        """처리 완료 표시."""
        self._q.task_done()

    async def join(self) -> None:
        """전 작업 완료 대기."""
        await self._q.join()


# SHUTDOWN은 object()라 프로세스마다 identity가 달라 pickle을 그대로 태우면 워커의
# `job is SHUTDOWN` 식별이 깨진다 → 별도 마커로 왕복시켜 get()에서 로컬 SHUTDOWN으로 복원.
_SHUTDOWN_MARKER = b"__DOKKAEBI_QUEUE_SHUTDOWN__"


class RedisWorkQueue(WorkQueue):
    """Redis 리스트(LPUSH/BRPOP) 기반 작업 큐. 여러 프로세스가 같은 key를 공유해 put/get 가능
    (크로스 프로세스 분배 + 워커 프로세스 재시작에도 큐 내용 유지 = 내구성).

    job은 pickle로 직렬화 — 내부 배치 파이프라인 전용(신뢰 경계 밖 입력을 이 큐에 넣지 말 것).
    Redis 연결 오류는 (RedisCache와 달리) 그대로 올린다: 배치 작업은 조용히 유실시키면 안 되는
    영역이라 상위(run_workers의 handler try/except, 또는 재시도 로직)에서 처리하게 둔다.

    ⚠️ task_done()/join()은 이 인스턴스가 로컬로 put()한 작업 수만 추적한다(InMemoryWorkQueue와
    동일한 카운터 방식). 다른 프로세스가 넣거나 처리하는 작업은 이 join()에 안 잡힌다 —
    여러 프로세스 간 "전부 끝났다" 동기화가 필요하면 별도 신호(결과 큐·DB 완료 플래그 등)를 쓸 것.
    """

    def __init__(self, url: str, key: str) -> None:
        import redis.asyncio as aioredis

        self._r = aioredis.from_url(url)
        self._key = key
        self._local = asyncio.Queue()  # task_done/join 카운팅 전용 — job 데이터는 안 들고 있음

    async def put(self, job: Any) -> None:
        """작업 적재(pickle 직렬화 후 LPUSH)."""
        payload = _SHUTDOWN_MARKER if job is SHUTDOWN else pickle.dumps(job)
        await self._r.lpush(self._key, payload)
        self._local.put_nowait(None)

    async def get(self) -> Any:
        """작업 1건 꺼냄(BRPOP, 없으면 대기)."""
        _, raw = await self._r.brpop(self._key)
        return SHUTDOWN if raw == _SHUTDOWN_MARKER else pickle.loads(raw)

    def task_done(self) -> None:
        """처리 완료 표시(로컬 카운터, join()용)."""
        self._local.task_done()

    async def join(self) -> None:
        """이 인스턴스가 넣은 작업 기준 완료 대기(로컬 카운터 — 클래스 docstring 참고)."""
        await self._local.join()


async def run_workers(
    queue: WorkQueue,
    handler: Callable[[Any], Awaitable[None]],
    *,
    num_workers: int,
) -> None:
    """num_workers개 워커를 띄워 큐를 병렬 소비. 각 워커가 SHUTDOWN을 받으면 종료.

    - handler(job): 작업 1건 처리(async). 예외는 잡아 로깅 후 다음 작업 진행(워커 안 죽음).
    - 고처리량 배치(임베딩·시나리오 사전생성)를 워커 형식으로 돌릴 때 사용.
    """
    async def _worker(wid: int) -> None:
        while True:
            job = await queue.get()
            if job is SHUTDOWN:
                queue.task_done()
                return
            try:
                await handler(job)
            except Exception:  # 한 작업 실패가 워커/배치를 멈추지 않게
                logger.exception("worker %d 작업 실패: %r", wid, job)
            finally:
                queue.task_done()

    await asyncio.gather(*[_worker(i) for i in range(num_workers)])


async def stop_workers(queue: WorkQueue, num_workers: int) -> None:
    """워커 수만큼 SHUTDOWN 센티넬을 넣어 run_workers를 정상 종료시킨다."""
    for _ in range(num_workers):
        await queue.put(SHUTDOWN)


async def process_batch(
    jobs: Sequence[Any],
    handler: Callable[[Any], Awaitable[None]],
    *,
    num_workers: int,
) -> None:
    """리스트 jobs를 num_workers 워커로 병렬 처리 후 종료 (원샷 배치 헬퍼).

    - 결과 수집이 필요 없는 side-effect 작업(임베딩 적재·DB 저장 등)에 적합.
    - 결과를 모아야 하면 core.concurrency.bounded_gather를 쓸 것.
    """
    q = InMemoryWorkQueue()
    for j in jobs:
        await q.put(j)
    await stop_workers(q, num_workers)        # 워커가 다 비우면 빠져나가도록 센티넬
    await run_workers(q, handler, num_workers=num_workers)
