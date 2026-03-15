"""Warm reader screenshots hosted on shots.waylonwalker.com."""

from __future__ import annotations

import argparse
import concurrent.futures
import time
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser

DEFAULT_READER_URL = "https://go.waylonwalker.com/reader/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
DEFAULT_SHOTS_HOST = "shots.waylonwalker.com"


def _as_float(value: object) -> float:
    """Return a numeric value as float when possible."""
    return float(value) if isinstance(value, (int, float)) else 0.0


@dataclass(frozen=True)
class CrawlResult:
    """Collected reader page and image URLs."""

    page_urls: list[str]
    shot_image_urls: list[str]
    external_image_urls: list[str]


class ReaderPageParser(HTMLParser):
    """Collect reader pagination links and image sources."""

    def __init__(self, page_url: str, shots_host: str) -> None:
        super().__init__()
        self.page_url = page_url
        self.shots_host = shots_host
        self.shot_image_urls: list[str] = []
        self.external_image_urls: list[str] = []
        self.reader_page_urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)

        if tag == "img":
            src = attr_map.get("src")
            if not src:
                return
            resolved = urllib.parse.urljoin(self.page_url, src)
            parsed = urllib.parse.urlparse(resolved)
            if parsed.netloc == self.shots_host and parsed.path.rstrip("/") == "/shot":
                self.shot_image_urls.append(resolved)
            else:
                self.external_image_urls.append(resolved)
            return

        if tag != "a":
            return

        href = attr_map.get("href")
        if not href:
            return

        resolved = urllib.parse.urljoin(self.page_url, href)
        if is_reader_page_url(resolved):
            self.reader_page_urls.append(resolved)


def is_reader_page_url(url: str) -> bool:
    """Return True when URL points to a reader index page."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    normalized_path = parsed.path.rstrip("/") or "/"
    return normalized_path == "/reader" or normalized_path.startswith("/reader/page/")


def fetch_text(url: str, timeout: float, user_agent: str) -> str:
    """Fetch text content from a URL."""
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def crawl_reader_pages(
    start_url: str,
    timeout: float,
    user_agent: str,
    shots_host: str,
    page_limit: int = 0,
) -> CrawlResult:
    """Crawl reader pages and collect screenshot URLs."""
    pending = [start_url]
    seen_pages: set[str] = set()
    seen_shots: set[str] = set()
    seen_external: set[str] = set()
    page_urls: list[str] = []
    shot_image_urls: list[str] = []
    external_image_urls: list[str] = []

    while pending:
        page_url = pending.pop(0)
        if page_url in seen_pages:
            continue
        seen_pages.add(page_url)

        html = fetch_text(page_url, timeout=timeout, user_agent=user_agent)
        parser = ReaderPageParser(page_url=page_url, shots_host=shots_host)
        parser.feed(html)

        page_urls.append(page_url)

        for image_url in parser.shot_image_urls:
            if image_url not in seen_shots:
                seen_shots.add(image_url)
                shot_image_urls.append(image_url)

        for image_url in parser.external_image_urls:
            if image_url not in seen_external:
                seen_external.add(image_url)
                external_image_urls.append(image_url)

        if page_limit and len(page_urls) >= page_limit:
            continue

        for next_page_url in parser.reader_page_urls:
            if next_page_url not in seen_pages and next_page_url not in pending:
                pending.append(next_page_url)

    return CrawlResult(
        page_urls=page_urls,
        shot_image_urls=shot_image_urls,
        external_image_urls=external_image_urls,
    )


def build_trigger_shot_url(image_url: str) -> str:
    """Convert a /shot URL into a /trigger/shot URL."""
    parsed = urllib.parse.urlparse(image_url)
    normalized_path = parsed.path.rstrip("/")
    if normalized_path != "/shot":
        raise ValueError(f"Expected /shot URL, got: {image_url}")

    return urllib.parse.urlunparse(parsed._replace(path="/trigger/shot"))


def queue_shot(
    image_url: str,
    timeout: float,
    user_agent: str,
) -> dict[str, object]:
    """Queue a screenshot job without waiting for render completion."""
    trigger_url = build_trigger_shot_url(image_url)
    started = time.perf_counter()
    req = urllib.request.Request(
        trigger_url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Cache-Control": "no-cache",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            elapsed_ms = (time.perf_counter() - started) * 1000
            payload = json.loads(response.read().decode("utf-8"))
            queue_status = payload.get("status", "unknown")
            return {
                "ok": queue_status in {"queued", "already_queued", "exists"},
                "status_code": response.status,
                "elapsed_ms": elapsed_ms,
                "image_url": image_url,
                "trigger_url": trigger_url,
                "queue_status": queue_status,
            }
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - started) * 1000
        detail = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status_code": exc.code,
            "elapsed_ms": elapsed_ms,
            "image_url": image_url,
            "trigger_url": trigger_url,
            "queue_status": "error",
            "error": detail,
        }
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - started) * 1000
        return {
            "ok": False,
            "status_code": 0,
            "elapsed_ms": elapsed_ms,
            "image_url": image_url,
            "trigger_url": trigger_url,
            "queue_status": "error",
            "error": str(exc),
        }


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Ensure shots.waylonwalker.com images used by reader pages are ready"
    )
    parser.add_argument("--reader-url", default=DEFAULT_READER_URL)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--page-limit", type=int, default=0)
    parser.add_argument("--image-limit", type=int, default=0)
    parser.add_argument("--shots-host", default=DEFAULT_SHOTS_HOST)
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent header used for requests",
    )
    return parser.parse_args()


def main() -> None:
    """Crawl the reader and warm matching screenshot images."""
    args = parse_args()
    started = time.perf_counter()

    crawl = crawl_reader_pages(
        start_url=args.reader_url,
        timeout=args.timeout,
        user_agent=args.user_agent,
        shots_host=args.shots_host,
        page_limit=args.page_limit,
    )
    image_urls = crawl.shot_image_urls
    if args.image_limit > 0:
        image_urls = image_urls[: args.image_limit]

    if not image_urls:
        raise SystemExit("No shots.waylonwalker.com reader images found")

    print("Ensure reader shots are ready")
    print(f"- reader_url: {args.reader_url}")
    print(f"- pages_crawled: {len(crawl.page_urls)}")
    print(f"- shot_images: {len(image_urls)}")
    print(f"- external_images_skipped: {len(crawl.external_image_urls)}")
    print(f"- concurrency: {args.concurrency}")
    print(f"- timeout_seconds: {args.timeout}")
    results: list[dict[str, object]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(queue_shot, image_url, args.timeout, args.user_agent)
            for image_url in image_urls
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    failures = [row for row in results if not row["ok"]]
    elapsed = [_as_float(row.get("elapsed_ms", 0.0)) for row in results]
    print("\nResults")
    print(f"- requests: {len(results)}")
    print(
        f"- avg_ms: {sum(elapsed) / len(elapsed):.2f}" if elapsed else "- avg_ms: 0.00"
    )
    print(f"- max_ms: {max(elapsed):.2f}" if elapsed else "- max_ms: 0.00")
    print(f"- failures: {len(failures)}")

    if failures:
        print("\nFirst 5 failures")
        for failure in failures[:5]:
            print(
                "- "
                f"code={failure['status_code']} "
                f"ms={_as_float(failure.get('elapsed_ms', 0.0)):.2f} "
                f"image={failure['image_url']} "
                f"error={failure.get('error', '')}"
            )
        raise SystemExit(1)

    wall_ms = (time.perf_counter() - started) * 1000
    print(f"\n- wall_time_ms: {wall_ms:.2f}")


if __name__ == "__main__":
    main()
