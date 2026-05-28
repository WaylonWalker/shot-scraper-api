import asyncio
import hashlib
from pathlib import Path
from typing import Optional, List, Any, Awaitable, cast

from fastapi import HTTPException
from pyppeteer import launch

from shot_scraper_api.config import config
from shot_scraper_api.console import console
from shot_scraper_api.s3 import LocalStorageClient


DEFAULT_NAVIGATION_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


_browser: Any = None
_browser_lock = asyncio.Lock()
_page_pool: asyncio.Queue[Any] | None = None
_page_pool_lock = asyncio.Lock()
_page_pool_size: int | None = None
_page_pool_created = 0
_render_limiter: asyncio.Semaphore | None = None
_render_limiter_size: int | None = None
_postprocess_limiter: asyncio.Semaphore | None = None
_postprocess_limiter_size: int | None = None


def _is_connection_closed_error(exc: Exception) -> bool:
    return "connection is closed" in str(exc).lower()


def _concurrency_limit(value: Optional[int]) -> int:
    if isinstance(value, int) and value > 0:
        return value
    return max(1, int(config.queue_processor_concurrency))


def _get_render_limiter() -> asyncio.Semaphore:
    global _render_limiter, _render_limiter_size
    size = _concurrency_limit(config.render_concurrency)
    if _render_limiter is None or _render_limiter_size != size:
        _render_limiter = asyncio.Semaphore(size)
        _render_limiter_size = size
    return _render_limiter


def _get_postprocess_limiter() -> asyncio.Semaphore:
    global _postprocess_limiter, _postprocess_limiter_size
    size = _concurrency_limit(config.postprocess_concurrency)
    if _postprocess_limiter is None or _postprocess_limiter_size != size:
        _postprocess_limiter = asyncio.Semaphore(size)
        _postprocess_limiter_size = size
    return _postprocess_limiter


def reset_stage_limiters() -> None:
    global _render_limiter, _render_limiter_size
    global _postprocess_limiter, _postprocess_limiter_size
    global _page_pool, _page_pool_size, _page_pool_created
    _render_limiter = None
    _render_limiter_size = None
    _postprocess_limiter = None
    _postprocess_limiter_size = None
    _page_pool = None
    _page_pool_size = None
    _page_pool_created = 0


async def _launch_browser() -> Any:
    return await launch(
        args=[
            "--no-sandbox",
            "--autoplay-policy=no-user-gesture-required",
            "--mute-audio",
        ]
    )


async def get_browser() -> Any:
    """Get or create the shared browser instance."""
    global _browser
    async with _browser_lock:
        browser = _browser
        is_connected = getattr(browser, "isConnected", None) if browser else None
        if browser is None or (callable(is_connected) and not is_connected()):
            _browser = await _launch_browser()
        return _browser


async def warm_browser() -> None:
    """Launch the shared browser ahead of time."""
    await get_browser()


async def close_browser() -> None:
    """Close the shared browser instance if one exists."""
    global _browser, _page_pool, _page_pool_size, _page_pool_created
    async with _browser_lock:
        if _page_pool is not None:
            while not _page_pool.empty():
                page = await _page_pool.get()
                try:
                    await page.close()
                except Exception:
                    pass
        _page_pool = None
        _page_pool_size = None
        _page_pool_created = 0
        if _browser is not None:
            await _browser.close()
            _browser = None


async def _ensure_page_pool() -> asyncio.Queue[Any]:
    global _page_pool, _page_pool_size, _page_pool_created
    async with _page_pool_lock:
        size = _concurrency_limit(config.render_concurrency)
        if _page_pool is None or _page_pool_size != size:
            if _page_pool is not None:
                while not _page_pool.empty():
                    page = await _page_pool.get()
                    try:
                        await page.close()
                    except Exception:
                        pass
            _page_pool = asyncio.Queue()
            _page_pool_size = size
            _page_pool_created = 0
        return _page_pool


async def acquire_page() -> Any:
    global _page_pool_created
    pool = await _ensure_page_pool()
    try:
        return pool.get_nowait()
    except asyncio.QueueEmpty:
        pass

    async with _page_pool_lock:
        size = _concurrency_limit(config.render_concurrency)
        if _page_pool_created < size:
            browser = await get_browser()
            page = await browser.newPage()
            _page_pool_created += 1
            return page

    return await pool.get()


async def release_page(page: Any, reusable: bool = True) -> None:
    pool = await _ensure_page_pool()
    is_closed = getattr(page, "isClosed", None)
    if not reusable or (callable(is_closed) and is_closed()):
        try:
            await page.close()
        except Exception:
            pass
        global _page_pool_created
        async with _page_pool_lock:
            _page_pool_created = max(0, _page_pool_created - 1)
        return
    try:
        await page.goto(
            "about:blank", {"waitUntil": "domcontentloaded", "timeout": 3000}
        )
    except Exception:
        pass
    await pool.put(page)


def build_image_name(
    url: str,
    selector_list: List[str],
    width: int,
    height: int,
    scaled_width: int,
    scaled_height: int,
    format: str,
    version: Optional[int] = None,
    theme: Optional[str] = None,
) -> str:
    """Build a deterministic image filename."""
    version_str = f"v{version}" if version is not None else ""
    theme_str = f"theme:{theme}" if theme else ""
    imgname = (
        hashlib.md5(
            f"{url}{''.join(selector_list)}{version_str}{theme_str}".encode()
        ).hexdigest()
        + f"-{width}x{height}-{scaled_width}x{scaled_height}.{format}"
    ).lower()
    return imgname


async def take_screenshot(
    url: str,
    width: int,
    height: int,
    selector_list: list,
    output: str,
    timeout_ms: Optional[int] = None,
    theme: Optional[str] = None,
    capture_format: Optional[str] = None,
):
    """Take a screenshot of a webpage"""
    async with _get_render_limiter():
        for attempt in range(2):
            page = None
            reusable_page = True
            try:
                page = await acquire_page()

                # Set viewport
                await page.setViewport({"width": width, "height": height})
                await page.setExtraHTTPHeaders(DEFAULT_NAVIGATION_HEADERS)

                normalized_theme = (theme or "").strip().lower()
                if normalized_theme in ["dark", "light"]:
                    page_any: Any = page
                    emulate_media_features = getattr(
                        page_any, "emulateMediaFeatures", None
                    )
                    if callable(emulate_media_features):
                        emulate_result = emulate_media_features(
                            [
                                {
                                    "name": "prefers-color-scheme",
                                    "value": normalized_theme,
                                }
                            ]
                        )
                        if asyncio.iscoroutine(emulate_result):
                            await cast(Awaitable[Any], emulate_result)
                    else:
                        console.log(
                            "emulateMediaFeatures unavailable in this pyppeteer build; using CSS fallback"
                        )

                # Navigate to URL with custom timeout
                page_timeout = timeout_ms if timeout_ms else 30000
                await page.goto(
                    url, {"waitUntil": "domcontentloaded", "timeout": page_timeout}
                )

                if normalized_theme in ["dark", "light"]:
                    await page.evaluate(
                        """
                        (targetTheme) => {
                            document.documentElement.style.colorScheme = targetTheme;
                            document.documentElement.setAttribute('data-shot-theme', targetTheme);
                        }
                        """,
                        normalized_theme,
                    )

                for selector in selector_list:
                    try:
                        await page.waitForSelector(selector, {"timeout": 5000})
                    except Exception:
                        console.log(f"Selector {selector} not found")

                media_wait_timeout = min(timeout_ms, 5000) if timeout_ms else 5000

                try:
                    await page.evaluate("""
                        () => {
                            const isVisible = (el) => {
                                const rect = el.getBoundingClientRect();
                                const style = window.getComputedStyle(el);
                                const onScreen =
                                    rect.bottom > 0 &&
                                    rect.right > 0 &&
                                    rect.top < window.innerHeight &&
                                    rect.left < window.innerWidth;
                                const visible =
                                    rect.width > 0 &&
                                    rect.height > 0 &&
                                    style.display !== 'none' &&
                                    style.visibility !== 'hidden';
                                return onScreen && visible;
                            };

                            const videos = Array.from(document.querySelectorAll('video')).filter(isVisible);
                            console.log(`Found ${videos.length} video elements`);

                            videos.forEach((video, index) => {
                                video.muted = true;
                                video.playsInline = true;
                                video.autoplay = true;
                                video.preload = video.preload || 'auto';

                                if (video.readyState >= 1 && video.currentTime === 0) {
                                    try {
                                        video.currentTime = 0.05;
                                    } catch (err) {
                                    }
                                }

                                video.play().then(() => {
                                    console.log(`Video ${index} started playing`);
                                }).catch(err => {
                                    console.log(`Video ${index} play failed:`, err.message);
                                });
                            });

                            return videos.length > 0;
                        }
                    """)

                    if timeout_ms:
                        console.log(
                            f"Waiting {media_wait_timeout}ms for videos to load..."
                        )
                        await page.waitForFunction(
                            """
                            () => {
                                const isVisible = (el) => {
                                    const rect = el.getBoundingClientRect();
                                    const style = window.getComputedStyle(el);
                                    const onScreen =
                                        rect.bottom > 0 &&
                                        rect.right > 0 &&
                                        rect.top < window.innerHeight &&
                                        rect.left < window.innerWidth;
                                    const visible =
                                        rect.width > 0 &&
                                        rect.height > 0 &&
                                        style.display !== 'none' &&
                                        style.visibility !== 'hidden';
                                    return onScreen && visible;
                                };

                                const videos = Array.from(document.querySelectorAll('video')).filter(isVisible);
                                if (videos.length === 0) return true;

                                return videos.some((video) => {
                                    const hasFrame = video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0;
                                    const hasStarted = video.currentTime > 0 || !video.paused || video.ended;
                                    return hasFrame && hasStarted;
                                });
                            }
                            """,
                            {"timeout": media_wait_timeout},
                        )
                    else:
                        await page.waitForFunction(
                            """
                            () => {
                                const isVisible = (el) => {
                                    const rect = el.getBoundingClientRect();
                                    const style = window.getComputedStyle(el);
                                    const onScreen =
                                        rect.bottom > 0 &&
                                        rect.right > 0 &&
                                        rect.top < window.innerHeight &&
                                        rect.left < window.innerWidth;
                                    const visible =
                                        rect.width > 0 &&
                                        rect.height > 0 &&
                                        style.display !== 'none' &&
                                        style.visibility !== 'hidden';
                                    return onScreen && visible;
                                };

                                const videos = Array.from(document.querySelectorAll('video')).filter(isVisible);
                                if (videos.length === 0) return true;
                                return videos.some((video) => {
                                    const hasFrame = video.readyState >= 2 && video.videoWidth > 0 && video.videoHeight > 0;
                                    const hasStarted = video.currentTime > 0 || !video.paused || video.ended;
                                    return hasFrame && hasStarted;
                                });
                            }
                            """,
                            {"timeout": 5000},
                        )

                except Exception as exc:
                    console.log(f"Video handling failed: {exc}")
                    await asyncio.sleep(1)

                screenshot_options: dict[str, Any] = {"path": output, "fullPage": False}
                if capture_format == "jpeg":
                    screenshot_options["type"] = "jpeg"
                    screenshot_options["quality"] = 80
                elif capture_format == "png":
                    screenshot_options["type"] = "png"

                await page.screenshot(screenshot_options)
                return True
            except Exception as exc:
                if _is_connection_closed_error(exc):
                    reusable_page = False
                    console.log(
                        "Browser connection closed; resetting browser and retrying"
                    )
                    await close_browser()
                    if attempt == 0:
                        continue
                console.log(f"Screenshot failed: {str(exc)}")
                return False
            finally:
                if page is not None:
                    await release_page(page, reusable=reusable_page)

    return False


async def _run_command(cmd: list[str]) -> None:
    console.log(f"running {cmd}")
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    console.log(stdout.decode())
    console.log(stderr.decode())


async def generate_image_data(
    url: str,
    width: int,
    height: int,
    selector_list: list,
    format: str,
    scaled_width: int,
    scaled_height: int,
    version: Optional[int] = None,
    timeout_ms: Optional[int] = None,
    theme: Optional[str] = None,
):
    """Generate image and return file path and format"""
    # Generate unique filename with version support
    imgname = build_image_name(
        url,
        selector_list,
        width,
        height,
        scaled_width,
        scaled_height,
        format,
        version,
        theme,
    )

    output = "/tmp/" + imgname.replace(format, "png")
    output_final = "/tmp/" + imgname
    capture_format: Optional[str] = None
    storage_client = config.s3_client

    if isinstance(storage_client, LocalStorageClient):
        output_final = str(storage_client.local_path(imgname))
        if format == "webp":
            output = "/tmp/" + imgname.replace(format, "png")
        else:
            output = output_final

    if scaled_width == width and scaled_height == height:
        if format == "jpg":
            output = output_final
            capture_format = "jpeg"
        elif format == "png":
            output = output_final
            capture_format = "png"

    # Check if exists in S3
    if storage_client.file_exists(imgname):
        return imgname, output_final, True  # exists in S3

    # Take screenshot
    screenshot_success = await take_screenshot(
        url,
        width,
        height,
        selector_list,
        output,
        timeout_ms,
        theme,
        capture_format,
    )
    if not screenshot_success:
        raise HTTPException(status_code=500, detail="Failed to take screenshot")

    async with _get_postprocess_limiter():
        # Resize if needed
        if Path(output).exists() and (scaled_width != width or scaled_height != height):
            await _run_command(
                [
                    "convert",
                    output,
                    "-resize",
                    f"{scaled_width}x{scaled_height}",
                    output,
                ]
            )

        # Convert to the requested format
        if output == output_final:
            cmd = None
        elif format == "webp":
            cmd = [
                "cwebp",
                "-q",
                "80",
                output,
                "-o",
                output_final,
            ]
        elif format == "jpg":
            cmd = [
                "convert",
                output,
                "-quality",
                "80",
                output_final,
            ]
        else:  # PNG - just copy the file
            cmd = ["cp", output, output_final]

        if cmd and Path(output).exists():
            await _run_command(cmd)

        # Upload to storage
        if Path(output_final).exists():
            print("putting", output_final, imgname)
            if not isinstance(storage_client, LocalStorageClient):
                await storage_client.upload_file(output_final, imgname)

    return imgname, output_final, False  # newly created
