#!/usr/bin/env python3
"""HEAD load test against shot endpoint using links from an RSS feed."""

import argparse
import concurrent.futures
import json
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter

DEFAULT_RSS_URL = "https://go.waylonwalker.com/archive/rss.xml"
DEFAULT_SHOT_URL = "https://shots-dev.wayl.one/shot/"
DEFAULT_STATS_URL = "https://shots-dev.wayl.one/queue/stats"
DEFAULT_V = "1"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def fetch_links(rss_url: str, count: int) -> list[str]:
    req = urllib.request.Request(rss_url, method="GET")
    with urllib.request.urlopen(req, timeout=20) as response:
        payload = response.read()

    root = ET.fromstring(payload)
    links: list[str] = []
    for item in root.findall(".//item"):
        link_node = item.find("link")
        if link_node is not None and link_node.text:
            links.append(link_node.text.strip())
        if len(links) >= count:
            break

    return links


def build_request_url(base_url: str, page_url: str, version: str) -> str:
    query = urllib.parse.urlencode(
        {
            "url": page_url,
            "width": 1200,
            "height": 600,
            "scaled_width": 1200,
            "scaled_height": 600,
            "format": "jpg",
            "v": version,
            "mode": "async",
        }
    )
    return f"{base_url}?{query}"


def run_head_request(url: str, timeout: float, user_agent: str) -> dict:
    started = time.perf_counter()
    req = urllib.request.Request(
        url,
        method="HEAD",
        headers={
            "User-Agent": user_agent,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://shots-dev.wayl.one/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            elapsed = (time.perf_counter() - started) * 1000
            headers = {k.lower(): v for k, v in response.headers.items()}
            return {
                "ok": True,
                "status_code": response.status,
                "elapsed_ms": elapsed,
                "shot_status": headers.get("x-screenshot-status", ""),
            }
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        headers = {k.lower(): v for k, v in exc.headers.items()} if exc.headers else {}
        return {
            "ok": False,
            "status_code": exc.code,
            "elapsed_ms": elapsed,
            "shot_status": headers.get("x-screenshot-status", ""),
            "error": str(exc),
        }
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "ok": False,
            "status_code": 0,
            "elapsed_ms": elapsed,
            "shot_status": "",
            "error": str(exc),
        }


def fetch_queue_stats(stats_url: str, timeout: float, user_agent: str) -> dict:
    req = urllib.request.Request(
        stats_url,
        method="GET",
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": "https://shots-dev.wayl.one/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def to_number(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return 0.0


def print_stats_delta(before: dict, after: dict) -> None:
    keys = [
        "queued",
        "processing",
        "completed",
        "failed",
        "total",
        "completed_last_hour",
        "avg_processing_time_seconds",
        "avg_terminal_time_seconds",
        "success_rate_percent",
    ]
    print("\nQueue stats delta")
    for key in keys:
        before_val = to_number(before.get(key, 0))
        after_val = to_number(after.get(key, 0))
        delta = after_val - before_val
        if abs(delta - int(delta)) < 0.00001:
            print(f"- {key}: {before_val:.0f} -> {after_val:.0f} (delta {delta:+.0f})")
        else:
            print(f"- {key}: {before_val:.3f} -> {after_val:.3f} (delta {delta:+.3f})")


def summarize(results: list[dict]) -> None:
    elapsed = [row["elapsed_ms"] for row in results]
    status_codes = Counter(row["status_code"] for row in results)
    shot_statuses = Counter(row["shot_status"] or "none" for row in results)
    failures = [row for row in results if not row["ok"]]

    print("\nResults")
    print(f"- requests: {len(results)}")
    print(f"- avg_ms: {statistics.fmean(elapsed):.2f}")
    print(f"- p95_ms: {sorted(elapsed)[int(len(elapsed) * 0.95) - 1]:.2f}")
    print(f"- max_ms: {max(elapsed):.2f}")
    print(f"- status_codes: {dict(status_codes)}")
    print(f"- x_screenshot_status: {dict(shot_statuses)}")
    print(f"- failures: {len(failures)}")

    if failures:
        print("\nFirst 5 failures")
        for failure in failures[:5]:
            print(
                f"- code={failure['status_code']} ms={failure['elapsed_ms']:.2f} error={failure.get('error', '')}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run HEAD load test for shot endpoint")
    parser.add_argument("--rss-url", default=DEFAULT_RSS_URL)
    parser.add_argument("--shot-url", default=DEFAULT_SHOT_URL)
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--stats-url", default=DEFAULT_STATS_URL)
    parser.add_argument(
        "--v",
        default=DEFAULT_V,
        help="Version value used in screenshot request query string",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent header used for requests",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    links = fetch_links(args.rss_url, args.count)
    if not links:
        raise SystemExit("No links found in RSS feed")

    request_urls = [build_request_url(args.shot_url, link, args.v) for link in links]

    print("HEAD load test")
    print(f"- rss_url: {args.rss_url}")
    print(f"- shot_url: {args.shot_url}")
    print(f"- count: {len(request_urls)}")
    print(f"- concurrency: {args.concurrency}")
    print(f"- timeout_seconds: {args.timeout}")
    print(f"- stats_url: {args.stats_url}")
    print(f"- v: {args.v}")
    print(f"- user_agent: {args.user_agent}")

    stats_before = fetch_queue_stats(args.stats_url, args.timeout, args.user_agent)

    started = time.perf_counter()
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(run_head_request, request_url, args.timeout, args.user_agent)
            for request_url in request_urls
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    wall_ms = (time.perf_counter() - started) * 1000
    summarize(results)
    print(f"\n- wall_time_ms: {wall_ms:.2f}")

    stats_after = fetch_queue_stats(args.stats_url, args.timeout, args.user_agent)
    print_stats_delta(stats_before, stats_after)


if __name__ == "__main__":
    main()
