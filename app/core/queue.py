# ============================================================
# [v1] 작업 큐 인터페이스 + 워커 풀
# pipeline: 공통 인프라 (고처리량 배치: 임베딩·시나리오 사전생성·수집)
# 구현(요약): WorkQueue 추상 인터페이스 + InMemoryWorkQueue(asyncio) +
#            run_workers(N개 워커 병렬 소비) + process_batch(원샷 배치 헬퍼).
#            외부 큐(Redis/SQS)는 같은 인터페이스로 교체 가능(파일 1개 추가)
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
import asyncio
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Sequence

from app.core.logger import get_logger

logger = get_logger(__name__)

# 워커 종료 신호용 센티넬 (큐에 넣으면 워커가 빠져나감)
SHUTDOWN = object()


class WorkQueue(ABC):
    """작업 큐 추상 인터페이스.

    구현체 교체로 인프로세스 ↔ 외부 큐(Redis/SQS) 전환:
      - InMemoryWorkQueue : 단일 프로세스·휘발성 (baseline)
      - (TODO) RedisWorkQueue/SqsWorkQueue : 크로스 프로세스·내구성·재시도
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
