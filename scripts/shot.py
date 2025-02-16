#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "typer",
#     "pyppeteer",
#     "pydantic",
#     "requests",
#     "pillow",
#     "boto3",
#     "shot-scraper-api @ /home/waylon/git/shot-scraper-api"
# ]
# ///

import asyncio
from pathlib import Path
from pydantic import BaseModel
from pyppeteer import launch
from shot_scraper_api.config import get_config
import subprocess
import time
import typer

app = typer.Typer()


class Screenshot(BaseModel):
    url: str
    width: int
    height: int
    output: str
    output_final: str
    selector_list: list[str] = []
    s3_key: str | None = None


async def take_screenshots(
    screenshots: list[Screenshot],
    concurrency: int = 60,
):
    """Capture screenshots of multiple URLs using multiple concurrent browser tabs."""
    # Get config and S3 client
    config = get_config()
    s3_client = config.s3_client

    # Launch browser once and use it for all requests
    browser = await launch(
        args=[
            "--no-sandbox",
            "--disable-extensions",
        ],
        headless=True,
    )

    async def process_screenshot(screenshot: Screenshot):
        """Handles individual URL screenshot with specific settings."""
        try:
            page = await browser.newPage()

            await page.setViewport(
                {"width": screenshot.width, "height": screenshot.height}
            )
            await page.setCacheEnabled(True)

            start_time = time.monotonic()
            await page.goto(
                screenshot.url, {"waitUntil": "domcontentloaded", "timeout": 15000}
            )
            await page.evaluate("document.fonts.ready")
            load_time = time.monotonic() - start_time

            # Wait for selectors if specified
            for selector in screenshot.selector_list:
                try:
                    await page.waitForSelector(selector, {"timeout": 5000})
                except:
                    typer.echo(f"Selector {selector} not found")

            # Take screenshot
            await page.screenshot(
                {
                    "path": screenshot.output,
                    "fullPage": False,
                    "type": "png",
                }
            )
            screenshot_time = time.monotonic() - start_time - load_time
            await page.close()

            # Convert using appropriate tool based on format
            if screenshot.output_final.endswith(".webp"):
                # WebP optimization:
                # -q 75: Good balance of quality and compression
                # -m 6: Maximum compression effort
                # -af: Enable auto-filter for better quality
                # -sharp_yuv: Use sharp RGB->YUV conversion
                cmd = [
                    "cwebp",
                    "-q",
                    "75",
                    "-m",
                    "6",
                    "-af",
                    "-sharp_yuv",
                    screenshot.output,
                    "-o",
                    screenshot.output_final,
                ]
                subprocess.run(cmd, check=True)
            elif screenshot.output_final.endswith(".jpg"):
                # JPEG optimization:
                # -sampling-factor 4:2:0: Standard web chroma subsampling
                # -strip: Remove metadata
                # -interlace Plane: Progressive loading
                # -quality 80: Good quality while maintaining compression
                # -define jpeg:dct-method=float: Higher quality encoding
                cmd = [
                    "convert",
                    screenshot.output,
                    "-sampling-factor",
                    "4:2:0",
                    "-strip",
                    "-interlace",
                    "Plane",
                    "-quality",
                    "80",
                    "-define",
                    "jpeg:dct-method=float",
                    screenshot.output_final,
                ]
                subprocess.run(cmd, check=True)
            elif screenshot.output_final.endswith(".png"):
                # PNG optimization:
                # Using optipng for better compression
                # -o2: Optimization level 2 (good balance of speed/compression)
                # -strip all: Remove all metadata
                cmd = [
                    "optipng",
                    "-o2",
                    "-strip",
                    "all",
                    "-out",
                    screenshot.output_final,
                    screenshot.output,
                ]
                subprocess.run(cmd, check=True)
            elif screenshot.output != screenshot.output_final:
                # Fallback copy if formats match but paths differ
                cmd = ["cp", screenshot.output, screenshot.output_final]
                subprocess.run(cmd, check=True)

            # Upload to S3 if configured
            if config.aws_bucket_name and screenshot.s3_key:
                await s3_client.upload_file(
                    filepath=screenshot.output_final,
                    filename=screenshot.s3_key,
                )
                typer.echo(f"Uploaded to S3: {screenshot.s3_key}")

            typer.echo(
                f"Saved screenshot: {screenshot.output_final} (Load time: {load_time:.2f} seconds, Screenshot time: {screenshot_time:.2f} seconds)"
            )
        except Exception as e:
            typer.echo(f"Failed to capture {screenshot.url}: {e}")

    # Process URLs in parallel with a limited number of concurrent tabs
    semaphore = asyncio.Semaphore(concurrency)

    async def sem_task(screenshot):
        """Ensures tasks run within concurrency limits."""
        async with semaphore:
            await process_screenshot(screenshot)

    await asyncio.gather(*[sem_task(screenshot) for screenshot in screenshots])
    await browser.close()


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
    output.mkdir(parents=True, exist_ok=True)
    screenshots = []

    for url in urls:
        safe_filename = (
            url.replace("https://", "").replace("http://", "").replace("/", "_")
        )
        screenshots.append(
            Screenshot(
                url=url,
                width=width,
                height=height,
                output=str(output / f"{safe_filename}.png"),
                output_final=str(output / f"{safe_filename}.png"),
            )
        )

    asyncio.run(take_screenshots(screenshots))


@app.command()
def capture_queue():
    """Process the screenshot queue using a single browser instance."""
    import requests

    # Get the queue from the API
    response = requests.get("http://localhost:8000/queue")
    queue = response.json()

    # Convert queue items to Screenshot models
    screenshots = []
    for filename, item in queue.items():
        screenshots.append(
            Screenshot(
                url=item["url"],
                width=item["width"],
                height=item["height"],
                output=item["output"],
                output_final=item["output_final"],
                selector_list=item.get("selector_list", []),
                s3_key=filename,  # Use the queue filename as the S3 key
            )
        )

    # Process all screenshots with a single browser instance
    asyncio.run(take_screenshots(screenshots))


if __name__ == "__main__":
    app()
