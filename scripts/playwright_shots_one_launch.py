#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "typer",
#     "playwright",
# ]
# ///

from pathlib import Path
from playwright.sync_api import sync_playwright
import typer

app = typer.Typer()


def take_screenshots(urls: list[str], output_dir: Path):
    """Capture screenshots of multiple URLs using a single browser instance."""
    output_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        for url in urls:
            safe_filename = (
                url.replace("https://", "").replace("http://", "").replace("/", "_")
            )
            screenshot_path = output_dir / f"{safe_filename}.png"

            page.goto(url, wait_until="networkidle")
            page.screenshot(path=screenshot_path)
            typer.echo(f"Saved screenshot: {screenshot_path}")

        browser.close()


@app.command()
def capture(urls: list[str], output: Path = Path("screenshots")):
    """
    Takes a list of URLs and captures screenshots for each one.
    Screenshots are saved in the 'output' directory.
    """
    take_screenshots(urls, output)


if __name__ == "__main__":
    app()
