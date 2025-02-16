#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "typer",
#     "pyppeteer",
# ]
# ///

import asyncio
from pathlib import Path
from pyppeteer import launch
import time
import typer

app = typer.Typer()


async def take_screenshots(
    urls: list[str],
    output_dir: Path,
    width: int = 1920,
    height: int = 1080,
    concurrency: int = 60,
):
    """Capture screenshots of multiple URLs using multiple concurrent browser tabs."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Launch browser once and use it for all requests
    browser = await launch(
        args=[
            "--no-sandbox",
            "--disable-extensions",
        ],
        headless=True,
    )

    async def process_url(url):
        """Handles individual URL screenshot inside a reusable page."""
        safe_filename = (
            url.replace("https://", "").replace("http://", "").replace("/", "_")
        )
        screenshot_path = output_dir / f"{safe_filename}.png"

        try:
            page = await browser.newPage()

            await page.setViewport({"width": width, "height": height})
            await page.setCacheEnabled(True)

            start_time = time.monotonic()
            await page.goto(url, {"waitUntil": "domcontentloaded", "timeout": 15000})
            # await page.goto(url, {"waitUntil": "networkidle0", "timeout": 30000})
            await page.evaluate("document.fonts.ready")
            load_time = time.monotonic() - start_time
            # sleep for 5 seconds
            # await asyncio.sleep(5)

            # await page.screenshot({"path": str(screenshot_path), "fullPage": False})
            full_page = False
            image_format = "webp"
            await page.screenshot(
                {
                    "path": str(screenshot_path),
                    "fullPage": full_page,
                    "type": "png",
                }
            )
            screenshot_time = time.monotonic() - start_time - load_time
            await page.close()  # Close page after capturing

            typer.echo(
                f"Saved screenshot: {screenshot_path} (Load time: {load_time:.2f} seconds, Screenshot time: {screenshot_time:.2f} seconds)"
            )
        except Exception as e:
            typer.echo(f"Failed to capture {url}: {e}")

    # Process URLs in parallel with a limited number of concurrent tabs
    semaphore = asyncio.Semaphore(concurrency)

    async def sem_task(url):
        """Ensures tasks run within concurrency limits."""
        async with semaphore:
            await process_url(url)

    await asyncio.gather(*[sem_task(url) for url in urls])

    await browser.close()  # Close browser when all tasks are done


@app.command()
def capture(
    urls: list[str],
    output: Path = Path("screenshots"),
    width: int = 800,
    height: int = 450,
):
    """
    Takes a list of URLs and captures screenshots for each one.
    Screenshots are saved in the 'output' directory.
    """

    asyncio.run(take_screenshots(urls, output, width, height))

@app.command()
def capture_queue():
    # get queue from shot_scraper_api/api/app.py



if __name__ == "__main__":
    app()
