"""Warm sitemap-driven Open Graph screenshots on shots.waylonwalker.com."""

from __future__ import annotations

import argparse
import concurrent.futures
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from shot_scraper_api.reader_shots import DEFAULT_USER_AGENT, queue_shot

DEFAULT_SITEMAP_URL = "https://go.waylonwalker.com/sitemap.xml"
OG_IMAGE_SPECS = (
    ("og", 1200, 600),
    ("twitter", 1280, 640),
)


def fetch_sitemap_urls(sitemap_url: str, timeout: float, user_agent: str) -> list[str]:
    """Return page URLs from a sitemap XML document."""
    req = urllib.request.Request(sitemap_url, headers={"User-Agent": user_agent})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        xml_data = response.read().lstrip()

    root = ET.fromstring(xml_data)
    namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = [
        loc.text.strip()
        for loc in root.findall("sm:url/sm:loc", namespace)
        if loc.text and loc.text.strip()
    ]
    return urls


def build_og_page_url(page_url: str) -> str:
    """Return the derived /og/ page URL for a page."""
    parsed = urllib.parse.urlparse(page_url)
    base_path = parsed.path
    if not base_path.endswith("/"):
        base_path = f"{base_path}/"
    og_path = urllib.parse.urljoin(base_path, "og/")
    return urllib.parse.urlunparse(
        parsed._replace(path=og_path, params="", query="", fragment="")
    )


def build_og_shot_urls(page_url: str) -> list[str]:
    """Return the og/twitter shot URLs for a sitemap page."""
    og_page_url = build_og_page_url(page_url)
    shot_urls: list[str] = []
    for _label, width, height in OG_IMAGE_SPECS:
        query = urllib.parse.urlencode(
            {
                "url": og_page_url,
                "height": height,
                "width": width,
                "scaled_width": width,
                "scaled_height": height,
                "format": "jpg",
            }
        )
        shot_urls.append(f"https://shots.waylonwalker.com/shot/?{query}")
    return shot_urls


def collect_sitemap_og_shots(page_urls: list[str]) -> list[str]:
    """Return de-duplicated shot URLs for every sitemap page."""
    seen: set[str] = set()
    shot_urls: list[str] = []
    for page_url in page_urls:
        for shot_url in build_og_shot_urls(page_url):
            if shot_url not in seen:
                seen.add(shot_url)
                shot_urls.append(shot_url)
    return shot_urls


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Ensure sitemap-driven Open Graph screenshots are ready"
    )
    parser.add_argument("--sitemap-url", default=DEFAULT_SITEMAP_URL)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent header used for requests",
    )
    return parser.parse_args()


def main() -> None:
    """Warm all derived OG screenshots from sitemap URLs."""
    args = parse_args()

    page_urls = fetch_sitemap_urls(args.sitemap_url, args.timeout, args.user_agent)
    if args.limit > 0:
        page_urls = page_urls[: args.limit]

    shot_urls = collect_sitemap_og_shots(page_urls)
    if not shot_urls:
        raise SystemExit("No sitemap URLs found")

    print("Ensure sitemap OG shots are ready")
    print(f"- sitemap_url: {args.sitemap_url}")
    print(f"- pages: {len(page_urls)}")
    print(f"- shots: {len(shot_urls)}")
    print(f"- concurrency: {args.concurrency}")
    print(f"- timeout_seconds: {args.timeout}")
    results: list[dict[str, object]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(queue_shot, shot_url, args.timeout, args.user_agent)
            for shot_url in shot_urls
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    failures = [row for row in results if not row["ok"]]
    print("\nResults")
    print(f"- requests: {len(results)}")
    print(f"- failures: {len(failures)}")

    if failures:
        print("\nFirst 5 failures")
        for failure in failures[:5]:
            print(
                "- "
                f"code={failure['status_code']} "
                f"image={failure['image_url']} "
                f"error={failure.get('error', '')}"
            )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
