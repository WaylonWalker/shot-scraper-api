import asyncio
import signal

from shot_scraper_api.console import console
from shot_scraper_api.processor import start_queue_processor, stop_queue_processor
from shot_scraper_api.worker_health import heartbeat_loop


async def main() -> None:
    await start_queue_processor()
    console.log("Queue worker running")

    stop_event = asyncio.Event()
    heartbeat_task = asyncio.create_task(heartbeat_loop(stop_event))
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()
    heartbeat_task.cancel()
    try:
        await heartbeat_task
    except asyncio.CancelledError:
        pass
    await stop_queue_processor()
    console.log("Queue worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
