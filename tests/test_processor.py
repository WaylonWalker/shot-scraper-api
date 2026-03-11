import asyncio
from types import SimpleNamespace

from shot_scraper_api import processor as processor_module
from shot_scraper_api import screenshot as screenshot_module
from shot_scraper_api.queue import JobStatus, ScreenshotQueue


def test_queue_processor_starts_multiple_workers(monkeypatch):
    created = []

    class FakeTask:
        def cancel(self) -> None:
            return None

        def __await__(self):
            async def _done():
                return None

            return _done().__await__()

    def fake_create_task(coro):
        created.append(coro)
        coro.close()
        return FakeTask()

    monkeypatch.setattr(asyncio, "create_task", fake_create_task)
    monkeypatch.setattr(
        processor_module,
        "config",
        SimpleNamespace(queue_processor_concurrency=3),
    )

    processor = processor_module.QueueProcessor()
    asyncio.run(processor.start())

    assert len(created) == 3


def test_browser_is_reused_until_closed(monkeypatch):
    launches = []

    class FakeBrowser:
        def __init__(self) -> None:
            self.closed = False

        def isConnected(self) -> bool:
            return not self.closed

        async def close(self) -> None:
            self.closed = True

    async def fake_launch(*_args, **_kwargs):
        browser = FakeBrowser()
        launches.append(browser)
        return browser

    async def _exercise_browser():
        screenshot_module.reset_stage_limiters()
        await screenshot_module.close_browser()
        monkeypatch.setattr(screenshot_module, "launch", fake_launch)
        monkeypatch.setattr(
            screenshot_module,
            "config",
            SimpleNamespace(
                queue_processor_concurrency=1,
                render_concurrency=1,
                postprocess_concurrency=1,
            ),
        )

        first = await screenshot_module.get_browser()
        second = await screenshot_module.get_browser()
        await screenshot_module.close_browser()
        third = await screenshot_module.get_browser()
        await screenshot_module.close_browser()

        assert first is second
        assert third is not first

    asyncio.run(_exercise_browser())

    assert len(launches) == 2


def test_stage_limiters_follow_independent_config(monkeypatch):
    monkeypatch.setattr(
        screenshot_module,
        "config",
        SimpleNamespace(
            queue_processor_concurrency=6,
            render_concurrency=4,
            postprocess_concurrency=2,
        ),
    )
    screenshot_module.reset_stage_limiters()

    render_limiter = screenshot_module._get_render_limiter()
    postprocess_limiter = screenshot_module._get_postprocess_limiter()

    assert render_limiter._value == 4
    assert postprocess_limiter._value == 2


def test_page_pool_reuses_pages(monkeypatch):
    pages = []

    class FakePage:
        def __init__(self) -> None:
            self.closed = False
            self.visits = []

        async def goto(self, url: str, _options=None) -> None:
            self.visits.append(url)

        def isClosed(self) -> bool:
            return self.closed

        async def close(self) -> None:
            self.closed = True

    class FakeBrowser:
        def isConnected(self) -> bool:
            return True

        async def newPage(self) -> FakePage:
            page = FakePage()
            pages.append(page)
            return page

        async def close(self) -> None:
            return None

    async def fake_launch(*_args, **_kwargs):
        return FakeBrowser()

    async def _exercise_page_pool() -> None:
        screenshot_module.reset_stage_limiters()
        await screenshot_module.close_browser()
        monkeypatch.setattr(screenshot_module, "launch", fake_launch)
        monkeypatch.setattr(
            screenshot_module,
            "config",
            SimpleNamespace(
                queue_processor_concurrency=2,
                render_concurrency=2,
                postprocess_concurrency=1,
            ),
        )

        first = await screenshot_module.acquire_page()
        await screenshot_module.release_page(first)
        second = await screenshot_module.acquire_page()
        await screenshot_module.release_page(second)
        await screenshot_module.close_browser()

        assert first is second

    asyncio.run(_exercise_page_pool())

    assert len(pages) == 1
    assert pages[0].visits == ["about:blank", "about:blank"]


def test_screenshot_queue_cleans_stale_jobs(tmp_path):
    queue = ScreenshotQueue(cache_dir=str(tmp_path / "queue-cache"))

    completed_job = queue.add_job(url="https://example.com", priority=1)
    processing_job = queue.add_job(url="https://example.org", priority=1)
    queued_job = queue.add_job(url="https://example.net", priority=1)

    queue.update_job_status(completed_job, JobStatus.COMPLETED)
    queue.update_job_status(processing_job, JobStatus.PROCESSING)

    old = 1.0
    completed_data = queue.get_job(completed_job)
    processing_data = queue.get_job(processing_job)
    queued_data = queue.get_job(queued_job)
    assert completed_data and processing_data and queued_data

    completed_data["updated_at"] = old
    processing_data["started_processing_at"] = old
    processing_data["updated_at"] = old
    queued_data["created_at"] = old

    queue.cache.set(f"job:{completed_job}", completed_data)
    queue.cache.set(f"job:{processing_job}", processing_data)
    queue.cache.set(f"job:{queued_job}", queued_data)

    removed = queue.cleanup_old_jobs(max_age_hours=24, stale_age_minutes=30)

    assert removed == {"completed": 1, "failed": 0, "queued": 1, "processing": 1}
    assert queue.get_job(completed_job) is None
    assert queue.get_job(processing_job) is None
    assert queue.get_job(queued_job) is None
