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


def take_screenshot(url: str, output_dir: Path):
    """Capture a screenshot of the given URL and save it to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = (
        output_dir
        / f"{url.replace('https://', '').replace('http://', '').replace('/', '_')}.png"
    )

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        page.screenshot(path=filename)
        browser.close()

    typer.echo(f"Saved screenshot: {filename}")


@app.command()
def capture(urls: list[str], output: Path = Path("screenshots")):
    """
    Takes a list of URLs and captures screenshots for each one.
    Screenshots are saved in the 'output' directory.
    """
    for url in urls:
        take_screenshot(url, output)


if __name__ == "__main__":
    app()
