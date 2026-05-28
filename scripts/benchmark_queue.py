#!/usr/bin/env python3
"""Benchmark queue drain time and processing time for a batch of shots."""

import argparse
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from queue_well_known_links import (
    build_trigger_url,
    extract_urls,
    fetch_link_rows,
    queue_url,
)


def fetch_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark queue throughput")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument(
        "--links-url",
        default="https://go.waylonwalker.com/.well-known/links",
    )
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--request-concurrency", type=int, default=25)
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument(
        "--field", choices=["targetUrl", "sourceUrl"], default="targetUrl"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    start_stats = fetch_json(f"{base_url}/queue/stats")

    rows = fetch_link_rows(args.links_url, args.timeout)
    urls = extract_urls(rows, args.field)[: args.limit]
    request_urls = [
        build_trigger_url(f"{base_url}/trigger/shot", url, str(args.version))
        for url in urls
    ]

    start = time.time()
    results = []
    with ThreadPoolExecutor(max_workers=args.request_concurrency) as pool:
        futures = [
            pool.submit(queue_url, request_url, args.timeout, "benchmark")
            for request_url in request_urls
        ]
        for future in as_completed(futures):
            results.append(future.result())
    queue_done = time.time()

    target_completed = start_stats["completed"] + len(request_urls)
    while True:
        stats = fetch_json(f"{base_url}/queue/stats")
        if (
            stats["queued"] == 0
            and stats["processing"] == 0
            and stats["completed"] >= target_completed
        ):
            break
        time.sleep(args.poll_interval)
    end = time.time()

    queue_statuses = {}
    for result in results:
        queue_statuses[result["queue_status"]] = (
            queue_statuses.get(result["queue_status"], 0) + 1
        )

    output = {
        "urls": len(request_urls),
        "queue_statuses": queue_statuses,
        "request_avg_ms": round(
            sum(result["elapsed_ms"] for result in results) / len(results), 2
        ),
        "request_wall_s": round(queue_done - start, 2),
        "drain_s": round(end - start, 2),
        "completed_delta": stats["completed"] - start_stats["completed"],
        "avg_processing_time_seconds": stats["avg_processing_time_seconds"],
        "avg_terminal_time_seconds": stats["avg_terminal_time_seconds"],
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
