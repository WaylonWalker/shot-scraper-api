import asyncio
import signal

from shot_scraper_api.console import console
from shot_scraper_api.processor import start_queue_processor, stop_queue_processor


async def main() -> None:
    await start_queue_processor()
    console.log("Queue worker running")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()
    await stop_queue_processor()
    console.log("Queue worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
