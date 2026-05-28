#!/usr/bin/env python3
"""Benchmark one API process plus multiple queue worker processes."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def wait_for_url(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except urllib.error.URLError:
            time.sleep(0.25)
    raise RuntimeError(f"Timed out waiting for {url}")


def terminate_processes(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is None:
            process.send_signal(signal.SIGTERM)
    deadline = time.time() + 10
    for process in processes:
        while process.poll() is None and time.time() < deadline:
            time.sleep(0.1)
        if process.poll() is None:
            process.kill()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark a multi-process local setup"
    )
    parser.add_argument("--port", type=int, default=5002)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--worker-concurrency", type=int, default=4)
    parser.add_argument("--render-concurrency", type=int, default=4)
    parser.add_argument("--postprocess-concurrency", type=int, default=2)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--request-concurrency", type=int, default=25)
    parser.add_argument("--version", type=int, required=True)
    parser.add_argument("--storage-dir", default=".cache/shots-multiproc")
    parser.add_argument("--queue-cache-dir", default=".cache/queue-multiproc")
    parser.add_argument("--namespace", default="bench-multiproc")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_url = f"http://127.0.0.1:{args.port}"
    log_dir = ROOT / ".cache" / "bench-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    storage_dir = ROOT / args.storage_dir
    queue_cache_dir = ROOT / args.queue_cache_dir

    if storage_dir.exists():
        subprocess.run(["rm", "-rf", str(storage_dir)], check=True)
    if queue_cache_dir.exists():
        subprocess.run(["rm", "-rf", str(queue_cache_dir)], check=True)
    storage_dir.parent.mkdir(parents=True, exist_ok=True)
    queue_cache_dir.parent.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.update(
        {
            "ENV": "prod",
            "STORAGE_BACKEND": "local",
            "LOCAL_STORAGE_DIR": str(storage_dir),
            "CACHE_DIR": str(queue_cache_dir),
            "QUEUE_PROCESSOR_ENABLED": "false",
            "QUEUE_NAMESPACE": args.namespace,
            "QUEUE_PROCESSOR_CONCURRENCY": str(args.worker_concurrency),
            "RENDER_CONCURRENCY": str(args.render_concurrency),
            "POSTPROCESS_CONCURRENCY": str(args.postprocess_concurrency),
        }
    )

    processes: list[subprocess.Popen] = []
    try:
        api_log = (log_dir / "api.log").open("w")
        api_process = subprocess.Popen(
            [
                "uv",
                "run",
                "uvicorn",
                "shot_scraper_api.api.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.port),
            ],
            cwd=ROOT,
            env=env,
            stdout=api_log,
            stderr=subprocess.STDOUT,
        )
        processes.append(api_process)

        wait_for_url(f"{base_url}/queue/stats")

        for index in range(args.workers):
            worker_log = (log_dir / f"worker-{index + 1}.log").open("w")
            worker_process = subprocess.Popen(
                ["uv", "run", "python", "scripts/run_queue_worker.py"],
                cwd=ROOT,
                env=env,
                stdout=worker_log,
                stderr=subprocess.STDOUT,
            )
            processes.append(worker_process)

        time.sleep(2)

        benchmark = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "scripts/benchmark_queue.py",
                "--base-url",
                base_url,
                "--limit",
                str(args.limit),
                "--request-concurrency",
                str(args.request_concurrency),
                "--version",
                str(args.version),
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )

        output = json.loads(benchmark.stdout)
        output["processes"] = {
            "api": 1,
            "workers": args.workers,
            "worker_concurrency": args.worker_concurrency,
            "render_concurrency": args.render_concurrency,
            "postprocess_concurrency": args.postprocess_concurrency,
        }
        print(json.dumps(output, indent=2))
    finally:
        terminate_processes(processes)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stdout or "")
        sys.stderr.write(exc.stderr or "")
        raise
