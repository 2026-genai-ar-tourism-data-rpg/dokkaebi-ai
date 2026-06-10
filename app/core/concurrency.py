# ============================================================
# [v1] 동시성 공통 유틸 — 세마포어 기반 병렬 처리 헬퍼
# pipeline: 공통 인프라 (LLM/외부 API 호출부에서 재사용)
# 구현(요약): 세마포어로 동시 실행 수를 제한하며 async worker를 병렬 실행(bounded_gather)
# 구현일: 2026-06-10 | 작성: kys (base-pipeline/kys/v1)
# ============================================================
import asyncio
from typing import Awaitable, Callable, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")


async def bounded_gather(
    items: Sequence[T],
    worker: Callable[[T], Awaitable[R]],
    *,
    limit: int,
) -> list[R]:
    """세마포어로 동시 실행 수를 limit으로 제한하며 worker를 병렬 실행.

    - items : 입력 목록
    - worker: async (item) -> result
    - limit : 동시 실행 상한 (config의 세마포어 개수에서 주입)
    반환: 입력 순서를 유지한 결과 리스트.
    """
    sem = asyncio.Semaphore(limit)

    async def _run(item: T) -> R:
        # 세마포어 획득 구간에서만 worker 실행 → 동시 실행 수 제한
        async with sem:
            return await worker(item)

    return await asyncio.gather(*[_run(i) for i in items])
