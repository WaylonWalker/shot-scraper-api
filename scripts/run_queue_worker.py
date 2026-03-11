#!/usr/bin/env python3
"""Run queue workers without starting the HTTP server."""

import asyncio
import signal

from shot_scraper_api.console import console
from shot_scraper_api.processor import stop_queue_processor, start_queue_processor
from shot_scraper_api.screenshot import close_browser, warm_browser


async def main() -> None:
    stop_event = asyncio.Event()

    def _handle_stop(*_args) -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for signame in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signame, _handle_stop)

    await start_queue_processor()
    await warm_browser()
    console.log("Queue worker ready")

    try:
        await stop_event.wait()
    finally:
        await stop_queue_processor()
        await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
