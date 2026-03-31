import asyncio
import os
import sys
import time
from typing import Optional

from shot_scraper_api.config import config
from shot_scraper_api.console import console
from shot_scraper_api.queue import get_queue


def get_worker_id() -> str:
    return os.environ.get("HOSTNAME", "unknown-worker")


def assess_worker_health(
    *,
    heartbeat_age_seconds: Optional[float],
    queued_jobs: int,
    processing_jobs: int,
    queued_oldest_age_seconds: float,
    heartbeat_timeout_seconds: int,
    stalled_queue_threshold_seconds: int,
    check_queue_stall: bool,
) -> tuple[bool, str]:
    if heartbeat_age_seconds is None:
        return False, "worker heartbeat missing"

    if heartbeat_age_seconds > heartbeat_timeout_seconds:
        return (
            False,
            f"worker heartbeat stale: age={heartbeat_age_seconds:.1f}s",
        )

    if (
        check_queue_stall
        and queued_jobs > 0
        and processing_jobs == 0
        and queued_oldest_age_seconds >= stalled_queue_threshold_seconds
    ):
        return (
            False,
            "queue stalled: "
            f"queued={queued_jobs} processing={processing_jobs} "
            f"oldest={queued_oldest_age_seconds:.1f}s",
        )

    return True, "ok"


async def heartbeat_loop(stop_event: asyncio.Event) -> None:
    queue = get_queue()
    worker_id = get_worker_id()

    while not stop_event.is_set():
        queue.record_worker_heartbeat(worker_id)
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=max(1, int(config.worker_heartbeat_interval_seconds)),
            )
        except asyncio.TimeoutError:
            continue


def run_probe(check_queue_stall: bool) -> int:
    queue = get_queue()
    worker_id = get_worker_id()
    heartbeat = queue.get_worker_heartbeat(worker_id)
    heartbeat_age = None if heartbeat is None else max(0.0, time.time() - heartbeat)
    stats = queue.get_queue_stats()
    healthy, detail = assess_worker_health(
        heartbeat_age_seconds=heartbeat_age,
        queued_jobs=int(stats.get("queued", 0)),
        processing_jobs=int(stats.get("processing", 0)),
        queued_oldest_age_seconds=float(stats.get("queued_oldest_age_seconds", 0.0)),
        heartbeat_timeout_seconds=max(1, int(config.worker_heartbeat_timeout_seconds)),
        stalled_queue_threshold_seconds=max(
            1, int(config.worker_stalled_queue_threshold_seconds)
        ),
        check_queue_stall=check_queue_stall,
    )
    if healthy:
        return 0

    console.log(f"Worker healthcheck failed for {worker_id}: {detail}")
    return 1


def main() -> None:
    check_queue_stall = "--queue-stall" in sys.argv
    raise SystemExit(run_probe(check_queue_stall=check_queue_stall))


if __name__ == "__main__":
    main()
