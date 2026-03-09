from types import SimpleNamespace

from fastapi.testclient import TestClient

from shot_scraper_api.api import app as app_module
from shot_scraper_api.api.app import app
from shot_scraper_api.queue import JobStatus, ScreenshotQueue
from shot_scraper_api.screenshot import build_image_name


class FakeQueue:
    def __init__(self) -> None:
        self.url_stats = {}
        self.active_jobs = [
            {
                "job_id": "job-processing",
                "url": "https://example.com",
                "status": "processing",
                "priority": 5,
                "created_at": 1.0,
            },
            {
                "job_id": "job-queued",
                "url": "https://example.org",
                "status": "queued",
                "priority": 2,
                "created_at": 1.0,
            },
        ]

    def add_job(self, **_kwargs) -> str:
        return "job-1"

    def get_queue_stats(self):
        return {
            "queued": 1,
            "processing": 1,
            "completed": 4,
            "failed": 0,
            "queued_avg_age_seconds": 2.5,
            "queued_oldest_age_seconds": 4.0,
            "processing_avg_age_seconds": 1.5,
            "success_rate_percent": 100.0,
        }

    def get_url_stats(self):
        rows = sorted(
            self.url_stats.values(), key=lambda row: (-row["request_count"], row["url"])
        )
        return {
            "total_urls": len(rows),
            "total_requests": sum(row["request_count"] for row in rows),
            "urls": rows,
        }

    def get_active_jobs(self):
        return self.active_jobs

    def get_job_id_by_filename(self, _filename: str):
        return None

    def get_job(self, _job_id: str):
        return None

    def is_shot_queued_or_processing(self, *_args, **_kwargs) -> bool:
        return False

    def record_url_request(self, url: str, filename: str, method: str) -> None:
        row = self.url_stats.get(
            url,
            {
                "url": url,
                "request_count": 0,
                "filenames": [],
                "method_counts": {},
                "first_requested_at": 1.0,
                "last_requested_at": 1.0,
            },
        )
        row["request_count"] += 1
        if filename not in row["filenames"]:
            row["filenames"].append(filename)
            row["filenames"].sort()
        row["method_counts"][method] = row["method_counts"].get(method, 0) + 1
        self.url_stats[url] = row


def test_screenshot_queue_tracks_url_requests(tmp_path):
    queue = ScreenshotQueue(cache_dir=str(tmp_path / "queue-cache"))

    queue.record_url_request("https://example.com", "first.webp", "GET")
    queue.record_url_request("https://example.com", "first.webp", "HEAD")
    queue.record_url_request("https://example.com", "second.webp", "GET")
    queue.record_url_request("https://example.org", "third.webp", "POST")

    stats = queue.get_url_stats()

    assert stats["total_urls"] == 2
    assert stats["total_requests"] == 4
    assert stats["urls"][0]["url"] == "https://example.com"
    assert stats["urls"][0]["request_count"] == 3
    assert stats["urls"][0]["filenames"] == ["first.webp", "second.webp"]
    assert stats["urls"][0]["method_counts"] == {"GET": 2, "HEAD": 1}


def test_screenshot_queue_lists_active_jobs(tmp_path):
    queue = ScreenshotQueue(cache_dir=str(tmp_path / "queue-cache"))

    first_job = queue.add_job(url="https://example.com", priority=1)
    second_job = queue.add_job(url="https://example.org", priority=4)
    queue.update_job_status(second_job, status=JobStatus.PROCESSING)

    active_jobs = queue.get_active_jobs()

    assert [job["job_id"] for job in active_jobs] == [second_job, first_job]
    assert [job["status"] for job in active_jobs] == ["processing", "queued"]


def test_url_stats_endpoint_lists_tracked_urls(monkeypatch):
    queue = FakeQueue()
    fake_config = SimpleNamespace(
        queue_processor_enabled=False,
        s3_client=SimpleNamespace(file_exists=lambda _filename: False),
    )

    monkeypatch.setattr(app_module, "config", fake_config)
    monkeypatch.setattr(app_module, "get_queue", lambda: queue)

    expected_filename = build_image_name(
        "https://example.com",
        [],
        800,
        450,
        800,
        450,
        "webp",
        None,
        None,
    )

    with TestClient(app) as client:
        first = client.post("/trigger/shot", params={"url": "https://example.com"})
        second = client.post("/trigger/shot", params={"url": "https://example.com"})
        stats = client.get("/urls/stats")

    assert first.status_code == 200
    assert second.status_code == 200
    assert stats.status_code == 200
    assert stats.json() == {
        "total_urls": 1,
        "total_requests": 2,
        "urls": [
            {
                "url": "https://example.com",
                "request_count": 2,
                "filenames": [expected_filename],
                "method_counts": {"POST": 2},
                "first_requested_at": 1.0,
                "last_requested_at": 1.0,
            }
        ],
    }


def test_url_dashboard_renders_tracked_stats(monkeypatch):
    queue = FakeQueue()
    queue.record_url_request("https://example.com", "example.webp", "GET")
    queue.record_url_request("https://example.com", "example.webp", "GET")
    queue.record_url_request("https://example.org", "other.webp", "HEAD")

    fake_config = SimpleNamespace(
        queue_processor_enabled=False,
        aws_bucket_name=None,
        aws_endpoint_url=None,
        queue_backend="auto",
    )

    monkeypatch.setattr(app_module, "config", fake_config)
    monkeypatch.setattr(app_module, "get_queue", lambda: queue)
    monkeypatch.setattr(app_module.time, "time", lambda: 11.0)

    with TestClient(app) as client:
        response = client.get("/dashboard/urls")
        canonical = client.get("/dashboard")

    assert response.status_code == 200
    assert canonical.status_code == 200
    assert "URL dashboard" in response.text
    assert "Environment" in response.text
    assert "Bucket" in response.text
    assert "(not set)" in response.text
    assert "AWS S3 default" in response.text
    assert "Tracked URLs" in response.text
    assert "Total requests" in response.text
    assert "Queued avg age" in response.text
    assert "In flight" in response.text
    assert "job-processing" in response.text
    assert "/job/job-processing" in response.text
    assert "10.0s" in response.text
    assert "Processing now" in response.text
    assert "Auto-refreshes every 5 seconds." in response.text
    assert "https://example.com" in response.text
    assert "example.webp" in response.text
