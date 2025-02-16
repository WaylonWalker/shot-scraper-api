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
from typing import Optional
from pydantic import BaseModel, Field, field_validator, ValidationInfo
from pyppeteer import launch
from shot_scraper_api.config import get_config
import subprocess
import time
import typer
from concurrent.futures import ThreadPoolExecutor

app = typer.Typer()


class Screenshot(BaseModel):
    url: str
    width: int
    height: int
    output: str
    output_final: str
    selector_list: list[str] = []
    s3_key: str | None = None
    scaled_width: Optional[int] = None
    scaled_height: Optional[int] = None

    @property
    def needs_scaling(self) -> bool:
        """Check if image needs to be scaled."""
        return (
            self.scaled_width is not None 
            and self.scaled_height is not None
            and (self.scaled_width != self.width or self.scaled_height != self.height)
        )

    @field_validator("scaled_width", "scaled_height", mode="before")
    @classmethod
    def set_scaled_dimensions(cls, v: Optional[int], info: ValidationInfo) -> Optional[int]:
        """Set scaled dimensions if not provided, maintaining aspect ratio."""
        values = info.data
        if "width" not in values or "height" not in values:
            return v

        original_width = values["width"]
        original_height = values["height"]

        # If neither scaled dimension is provided, use original dimensions
        if values.get("scaled_width") is None and values.get("scaled_height") is None:
            if info.field_name == "scaled_width":
                return original_width
            return original_height

        # If one scaled dimension is provided, calculate the other maintaining aspect ratio
        if info.field_name == "scaled_width" and v is None and values.get("scaled_height"):
            scaled_height = values["scaled_height"]
            return int(original_width * (scaled_height / original_height))
        elif info.field_name == "scaled_height" and v is None and values.get("scaled_width"):
            scaled_width = values["scaled_width"]
            return int(original_height * (scaled_width / original_width))

        return v

    @field_validator("scaled_width", "scaled_height")
    @classmethod
    def validate_scaled_dimensions(cls, v: Optional[int], info: ValidationInfo) -> Optional[int]:
        """Ensure scaled dimensions maintain aspect ratio and fit within bounds."""
        if v is None:
            return v

        values = info.data
        original_width = values["width"]
        original_height = values["height"]
        original_ratio = original_width / original_height

        # Get both scaled dimensions
        scaled_width = v if info.field_name == "scaled_width" else values.get("scaled_width")
        scaled_height = v if info.field_name == "scaled_height" else values.get("scaled_height")

        if scaled_width and scaled_height:
            scaled_ratio = scaled_width / scaled_height
            if abs(original_ratio - scaled_ratio) > 0.01:  # Allow small rounding differences
                # Adjust dimensions to maintain aspect ratio within bounds
                if scaled_width / original_width < scaled_height / original_height:
                    # Width is the constraining factor
                    if info.field_name == "scaled_height":
                        new_height = int(scaled_width / original_ratio)
                        return new_height
                else:
                    # Height is the constraining factor
                    if info.field_name == "scaled_width":
                        new_width = int(scaled_height * original_ratio)
                        return new_width

        return v


def process_image(screenshot: Screenshot) -> bool:
    """Process a single image with the appropriate conversion tool."""
    try:
        start_time = time.monotonic()
        
        # Only resize if needed
        if screenshot.needs_scaling:
            typer.echo(f"Resizing to {screenshot.scaled_width}x{screenshot.scaled_height}")
            # Use ImageMagick's resize to maintain aspect ratio and fit within bounds
            # > means "scale down only if larger"
            # < means "scale up only if smaller"
            resize_cmd = [
                "convert",
                screenshot.output,
                "-resize",
                f"{screenshot.scaled_width}x{screenshot.scaled_height}>",  # Only scale down if larger
                "-background", "none",  # Transparent background for padding
                screenshot.output,
            ]
            subprocess.run(resize_cmd, check=True, capture_output=True)
            resize_time = time.monotonic() - start_time
            typer.echo(f"Resize time: {resize_time:.2f}s")
            start_time = time.monotonic()

        if screenshot.output_final.endswith(".webp"):
            # WebP optimization
            cmd = [
                "cwebp",
                "-q", "75",
                "-m", "6",
                "-af",
                "-sharp_yuv",
                screenshot.output,
                "-o",
                screenshot.output_final,
            ]
        elif screenshot.output_final.endswith(".jpg"):
            # JPEG optimization
            cmd = [
                "convert",
                screenshot.output,
                "-sampling-factor", "4:2:0",
                "-strip",
                "-interlace", "Plane",
                "-quality", "80",
                "-define", "jpeg:dct-method=float",
                screenshot.output_final,
            ]
        elif screenshot.output_final.endswith(".png"):
            # PNG optimization
            cmd = [
                "optipng",
                "-o2",
                "-strip", "all",
                "-out", screenshot.output_final,
                screenshot.output,
            ]
        elif screenshot.output != screenshot.output_final:
            # Fallback copy if formats match but paths differ
            cmd = ["cp", screenshot.output, screenshot.output_final]

        subprocess.run(cmd, check=True, capture_output=True)
        convert_time = time.monotonic() - start_time
        typer.echo(f"Convert time: {convert_time:.2f}s")
        return True
    except Exception as e:
        typer.echo(f"Failed to process image {screenshot.output}: {e}")
        return False


async def process_images(screenshots: list[Screenshot], executor: ThreadPoolExecutor):
    """Process multiple images concurrently using a thread pool."""
    loop = asyncio.get_event_loop()
    tasks = []
    for screenshot in screenshots:
        task = loop.run_in_executor(executor, process_image, screenshot)
        tasks.append(task)
    return await asyncio.gather(*tasks)


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

    # Create a thread pool for image processing
    with ThreadPoolExecutor(max_workers=min(32, len(screenshots))) as executor:
        async def process_screenshot(screenshot: Screenshot):
            """Handles individual URL screenshot with specific settings."""
            page = None
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
                    except Exception:
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

                typer.echo(
                    f"Captured {screenshot.url} (Load time: {load_time:.2f}s, Screenshot time: {screenshot_time:.2f}s)"
                )
                return screenshot
            except Exception as e:
                typer.echo(f"Failed to capture {screenshot.url}: {e}")
                return None
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass  # Ignore cleanup errors

        # Process URLs in parallel with a limited number of concurrent tabs
        semaphore = asyncio.Semaphore(concurrency)

        async def sem_task(screenshot):
            """Ensures tasks run within concurrency limits."""
            async with semaphore:
                return await process_screenshot(screenshot)

        try:
            # Take all screenshots concurrently
            captured = await asyncio.gather(*[sem_task(screenshot) for screenshot in screenshots])
        finally:
            try:
                await browser.close()
            except Exception:
                pass  # Ignore browser cleanup errors

        # Filter out failed screenshots
        successful_screenshots = [s for s in captured if s is not None]

        # Process all images concurrently
        typer.echo("Processing images...")
        processed = await process_images(successful_screenshots, executor)

        # Upload processed images to S3 concurrently
        typer.echo("Uploading to S3...")
        upload_tasks = []
        for screenshot, was_processed in zip(successful_screenshots, processed):
            if was_processed and config.aws_bucket_name and screenshot.s3_key:
                task = s3_client.upload_file(
                    filepath=screenshot.output_final,
                    filename=screenshot.s3_key,
                )
                upload_tasks.append(task)
        
        if upload_tasks:
            await asyncio.gather(*upload_tasks)


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
        try:
            # Extract dimensions, ensuring they are integers
            width = int(item.get("width", 1200))
            height = int(item.get("height", 600))
            scaled_width = int(item.get("scaled_width", width))
            scaled_height = int(item.get("scaled_height", height))

            # Only set scaled dimensions if they're different from original
            if scaled_width == width and scaled_height == height:
                scaled_width = None
                scaled_height = None

            screenshot = Screenshot(
                url=item["url"],
                width=width,
                height=height,
                output=item["output"],
                output_final=item["output_final"],
                selector_list=item.get("selector_list", []),
                s3_key=filename,
                scaled_width=scaled_width,
                scaled_height=scaled_height,
            )
            screenshots.append(screenshot)
            if screenshot.needs_scaling:
                typer.echo(f"Will scale: {screenshot.width}x{screenshot.height} -> {screenshot.scaled_width}x{screenshot.scaled_height}")
        except Exception as e:
            typer.echo(f"Failed to create Screenshot for {filename}: {e}")

    if not screenshots:
        typer.echo("No valid screenshots to process")
        return

    # Process all screenshots with a single browser instance
    asyncio.run(take_screenshots(screenshots))


if __name__ == "__main__":
    app()
