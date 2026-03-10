import asyncio
from types import SimpleNamespace

from shot_scraper_api import processor as processor_module
from shot_scraper_api import screenshot as screenshot_module


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
