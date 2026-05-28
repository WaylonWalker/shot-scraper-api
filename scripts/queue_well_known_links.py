#!/usr/bin/env python3
"""Queue screenshots for links from a .well-known/links JSON document."""

import argparse
import concurrent.futures
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter

DEFAULT_LINKS_URL = "https://go.waylonwalker.com/.well-known/links"
DEFAULT_TRIGGER_URL = "http://localhost:5000/trigger/shot"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
OG_WIDTH = 1200
OG_HEIGHT = 630


def fetch_link_rows(links_url: str, timeout: float) -> list[dict]:
    req = urllib.request.Request(links_url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if not isinstance(data, list):
        raise ValueError("Expected top-level JSON array from links document")
    return data


def extract_urls(rows: list[dict], field: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for row in rows:
        links = row.get("links", [])
        if not isinstance(links, list):
            continue
        for link in links:
            if not isinstance(link, dict):
                continue
            url = link.get(field)
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
    return urls


def build_trigger_url(trigger_url: str, page_url: str, version: str | None) -> str:
    query = {
        "url": page_url,
        "width": OG_WIDTH,
        "height": OG_HEIGHT,
        "scaled_width": OG_WIDTH,
        "scaled_height": OG_HEIGHT,
        "format": "jpg",
    }
    if version:
        query["v"] = version
    return f"{trigger_url}?{urllib.parse.urlencode(query)}"


def queue_url(url: str, timeout: float, user_agent: str) -> dict:
    started = time.perf_counter()
    req = urllib.request.Request(
        url,
        method="POST",
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            elapsed = (time.perf_counter() - started) * 1000
            payload = response.read().decode("utf-8")
            body = json.loads(payload)
            return {
                "ok": True,
                "status_code": response.status,
                "elapsed_ms": elapsed,
                "queue_status": body.get("status", "unknown"),
            }
    except urllib.error.HTTPError as exc:
        elapsed = (time.perf_counter() - started) * 1000
        detail = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status_code": exc.code,
            "elapsed_ms": elapsed,
            "queue_status": "error",
            "error": detail,
        }
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.perf_counter() - started) * 1000
        return {
            "ok": False,
            "status_code": 0,
            "elapsed_ms": elapsed,
            "queue_status": "error",
            "error": str(exc),
        }


def summarize(results: list[dict]) -> None:
    elapsed = [row["elapsed_ms"] for row in results]
    status_codes = Counter(row["status_code"] for row in results)
    queue_statuses = Counter(row["queue_status"] for row in results)
    failures = [row for row in results if not row["ok"]]

    print("\nResults")
    print(f"- requests: {len(results)}")
    print(
        f"- avg_ms: {sum(elapsed) / len(elapsed):.2f}" if elapsed else "- avg_ms: 0.00"
    )
    print(f"- max_ms: {max(elapsed):.2f}" if elapsed else "- max_ms: 0.00")
    print(f"- status_codes: {dict(status_codes)}")
    print(f"- queue_statuses: {dict(queue_statuses)}")
    print(f"- failures: {len(failures)}")

    if failures:
        print("\nFirst 5 failures")
        for failure in failures[:5]:
            print(
                f"- code={failure['status_code']} ms={failure['elapsed_ms']:.2f} error={failure.get('error', '')}"
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Queue screenshots for links from a .well-known/links document"
    )
    parser.add_argument("--links-url", default=DEFAULT_LINKS_URL)
    parser.add_argument("--trigger-url", default=DEFAULT_TRIGGER_URL)
    parser.add_argument(
        "--field",
        choices=["targetUrl", "sourceUrl"],
        default="targetUrl",
        help="Which URL field to screenshot from the links document",
    )
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--v", default=None, help="Optional screenshot version")
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="User-Agent header used for requests",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    rows = fetch_link_rows(args.links_url, args.timeout)
    urls = extract_urls(rows, args.field)
    if args.limit > 0:
        urls = urls[: args.limit]
    if not urls:
        raise SystemExit("No URLs found in links document")

    request_urls = [build_trigger_url(args.trigger_url, url, args.v) for url in urls]

    print("Queue well-known links")
    print(f"- links_url: {args.links_url}")
    print(f"- trigger_url: {args.trigger_url}")
    print(f"- field: {args.field}")
    print(f"- urls: {len(urls)}")
    print(f"- concurrency: {args.concurrency}")
    print(f"- timeout_seconds: {args.timeout}")
    print(f"- size: {OG_WIDTH}x{OG_HEIGHT}")
    print(f"- version: {args.v or 'none'}")

    started = time.perf_counter()
    results: list[dict] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(queue_url, request_url, args.timeout, args.user_agent)
            for request_url in request_urls
        ]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    summarize(results)
    wall_ms = (time.perf_counter() - started) * 1000
    print(f"\n- wall_time_ms: {wall_ms:.2f}")


if __name__ == "__main__":
    main()
