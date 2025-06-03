# /// script
#!/usr/bin/env -S uv run --quiet --script
# requires-python = ">=3.12"
# dependencies = [
#     "typer",
#     "pyppeteer",
# ]
# ///

import asyncio
import interpreters
import json
from pathlib import Path
from pyppeteer import launch
import time
import typer

app = typer.Typer()


async def process_url(url, output_dir, width, height, full_page, image_format):
    """Handles individual URL screenshot in an isolated subinterpreter."""
    safe_filename = url.replace("https://", "").replace("http://", "").replace("/", "_")
    screenshot_path = output_dir / f"{safe_filename}.{image_format}"

    try:
        browser = await launch(
            args=[
                "--no-sandbox",
                "--disable-extensions",
                "--disable-gpu-rasterization",
                "--use-gl=swiftshader",
            ],
            headless=True,
        )

        page = await browser.newPage()

        # Block unnecessary resources
        await page.setRequestInterception(True)
        page.on(
            "request",
            lambda req: asyncio.ensure_future(
                req.continue_()
                if req.resourceType in ["document", "script", "xhr"]
                else req.abort()
            ),
        )

        await page.setViewport({"width": width, "height": height})

        start_time = time.monotonic()
        await page.goto(url, {"waitUntil": "domcontentloaded", "timeout": 15000})
        await page.evaluate("document.fonts.ready")
        load_time = time.monotonic() - start_time

        await page.waitForTimeout(300)  # Allow UI to settle

        screenshot_start = time.monotonic()
        await page.screenshot(
            {
                "path": str(screenshot_path),
                "fullPage": full_page,
                "type": image_format,
                "quality": 80 if image_format == "jpeg" else None,
            }
        )
        screenshot_time = time.monotonic() - screenshot_start

        await browser.close()  # Close browser after capture

        return {
            "url": url,
            "screenshot": str(screenshot_path),
            "load_time": round(load_time, 2),
            "screenshot_time": round(screenshot_time, 2),
        }

    except Exception as e:
        return {"url": url, "error": str(e)}


def worker_process(serialized_data):
    """Executes screenshot tasks in a separate subinterpreter."""
    data = json.loads(serialized_data)
    asyncio.run(process_url(**data))


def chunked(lst, size):
    """Splits list into chunks of specified size."""
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


@app.command()
def capture(
    urls: list[str] = typer.Argument(..., help="List of URLs to capture"),
    output: Path = Path("screenshots"),
    width: int = 800,
    height: int = 250,
    concurrency: int = 4,  # Number of subinterpreters
    batch_size: int = 10,
    full_page: bool = False,
    image_format: str = "jpeg",
):
    """
    Takes a list of URLs and captures screenshots for each one using Python subinterpreters.
    Screenshots are saved in the 'output' directory.

    Options:
      --concurrency: Number of subinterpreters (default: 4).
      --batch-size: Number of URLs per subinterpreter (default: 10).
      --full-page: Capture the full page instead of just the viewport.
      --image-format: Choose between "jpeg" (default) or "png".
    """
    output.mkdir(parents=True, exist_ok=True)

    subinterpreter_ids = [interpreters.create() for _ in range(concurrency)]

    tasks = []
    for batch in chunked(urls, batch_size):
        for subinterp in subinterpreter_ids:
            data = json.dumps(
                {
                    "urls": batch,
                    "output_dir": str(output),
                    "width": width,
                    "height": height,
                    "full_page": full_page,
                    "image_format": image_format,
                }
            )
            task = interpreters.run_string(subinterp, f"worker_process({data!r})")
            tasks.append(task)

    # Wait for all tasks to complete
    for task in tasks:
        interpreters.join(task)

    typer.echo("✅ All screenshots captured successfully.")


if __name__ == "__main__":
    app()
