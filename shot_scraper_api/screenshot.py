import asyncio
import hashlib
import os
from pathlib import Path
from typing import Optional, List, Any, Awaitable, cast

from fastapi import HTTPException
from pyppeteer import launch

from shot_scraper_api.config import config
from shot_scraper_api.console import console


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
):
    """Take a screenshot of a webpage"""
    try:
        # Launch browser
        browser = await launch(
            args=[
                "--no-sandbox",
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio",
            ]
        )
        page = await browser.newPage()

        # Set viewport
        await page.setViewport({"width": width, "height": height})

        normalized_theme = (theme or "").strip().lower()
        if normalized_theme in ["dark", "light"]:
            page_any: Any = page
            emulate_media_features = getattr(page_any, "emulateMediaFeatures", None)
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
        await page.goto(url, {"waitUntil": "domcontentloaded", "timeout": page_timeout})

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

        # Wait for selectors if specified
        for selector in selector_list:
            try:
                await page.waitForSelector(selector, {"timeout": 5000})
            except:
                console.log(f"Selector {selector} not found")

        media_wait_timeout = min(timeout_ms, 5000) if timeout_ms else 5000

        # Enhanced video handling
        try:
            # Try to play visible videos and wait for a renderable frame
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

                    // Find visible video elements only
                    const videos = Array.from(document.querySelectorAll('video')).filter(isVisible);
                    console.log(`Found ${videos.length} video elements`);
                    
                    // Try to play each video
                    videos.forEach((video, index) => {
                        video.muted = true;  // Mute to avoid autoplay issues
                        video.playsInline = true;
                        video.autoplay = true;
                        video.preload = video.preload || 'auto';

                        // Nudge off exact 0s where some players draw blank poster frames.
                        if (video.readyState >= 1 && video.currentTime === 0) {
                            try {
                                video.currentTime = 0.05;
                            } catch (err) {
                                // Ignore seek failures
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

            # Wait for visible videos to have frame data before capture.
            if timeout_ms:
                console.log(f"Waiting {media_wait_timeout}ms for videos to load...")
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
                # Default 5 second wait for videos
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

        except Exception as e:
            console.log(f"Video handling failed: {e}")
            await asyncio.sleep(1)

        # Take screenshot
        await page.screenshot({"path": output, "fullPage": False})
        await browser.close()
        return True
    except Exception as e:
        console.log(f"Screenshot failed: {str(e)}")
        return False


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

    # Check if exists in S3
    if config.s3_client.file_exists(imgname):
        return imgname, output_final, True  # exists in S3

    # Take screenshot
    screenshot_success = await take_screenshot(
        url, width, height, selector_list, output, timeout_ms, theme
    )
    if not screenshot_success:
        raise HTTPException(status_code=500, detail="Failed to take screenshot")

    # Resize if needed
    if Path(output).exists() and (scaled_width != width or scaled_height != height):
        cmd = [
            "convert",
            output,
            "-resize",
            f"{scaled_width}x{scaled_height}",
            output,
        ]
        console.log(f"running {cmd}")
        resize_proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await resize_proc.communicate()
        console.log(stdout.decode())
        console.log(stderr.decode())

    # Convert to the requested format
    if format == "webp":
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

    if Path(output).exists():
        console.log(f"running {cmd}")
        convert_proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await convert_proc.communicate()
        console.log(stdout.decode())
        console.log(stderr.decode())

    # Upload to S3
    if Path(output_final).exists():
        print("putting", output_final, imgname)
        await config.s3_client.upload_file(output_final, imgname)

    return imgname, output_final, False  # newly created
