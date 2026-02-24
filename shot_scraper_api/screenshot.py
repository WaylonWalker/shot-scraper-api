import asyncio
import hashlib
import os
from pathlib import Path
from typing import Optional, List

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
) -> str:
    """Build a deterministic image filename."""
    version_str = f"v{version}" if version is not None else ""
    imgname = (
        hashlib.md5(f"{url}{''.join(selector_list)}{version_str}".encode()).hexdigest()
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
):
    """Take a screenshot of a webpage"""
    try:
        # Launch browser
        browser = await launch(args=["--no-sandbox"])
        page = await browser.newPage()

        # Set viewport
        await page.setViewport({"width": width, "height": height})

        # Navigate to URL with custom timeout
        page_timeout = timeout_ms if timeout_ms else 30000
        await page.goto(url, {"waitUntil": "domcontentloaded", "timeout": page_timeout})

        # Wait for selectors if specified
        for selector in selector_list:
            try:
                await page.waitForSelector(selector, {"timeout": 5000})
            except:
                console.log(f"Selector {selector} not found")

        media_wait_timeout = min(timeout_ms, 5000) if timeout_ms else 5000

        # Wait for visible images and fonts to settle before capture.
        try:
            await page.waitForFunction(
                """
                () => {
                    if (!document.fonts || !document.fonts.ready) {
                        return true;
                    }
                    return document.fonts.status === 'loaded';
                }
                """,
                {"timeout": media_wait_timeout},
            )
        except Exception as e:
            console.log(f"Font readiness wait skipped: {e}")

        try:
            await page.waitForFunction(
                """
                () => {
                    const visibleImages = Array.from(document.images).filter((img) => {
                        const rect = img.getBoundingClientRect();
                        const style = window.getComputedStyle(img);
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
                    });

                    if (visibleImages.length === 0) {
                        return true;
                    }

                    return visibleImages.every((img) => img.complete);
                }
                """,
                {"timeout": media_wait_timeout},
            )
        except Exception as e:
            console.log(f"Visible image wait skipped: {e}")

        # Enhanced video handling
        try:
            # Try to play videos and wait for them to be ready
            await page.evaluate("""
                () => {
                    // Find all video elements
                    const videos = document.querySelectorAll('video');
                    console.log(`Found ${videos.length} video elements`);
                    
                    // Try to play each video
                    videos.forEach((video, index) => {
                        video.muted = true;  // Mute to avoid autoplay issues
                        video.play().then(() => {
                            console.log(`Video ${index} started playing`);
                        }).catch(err => {
                            console.log(`Video ${index} play failed:`, err.message);
                        });
                    });
                    
                    return videos.length > 0;
                }
            """)

            # Wait for videos to be ready if timeout is specified
            if timeout_ms:
                console.log(f"Waiting {media_wait_timeout}ms for videos to load...")
                await page.waitForFunction(
                    """
                    () => {
                        const videos = document.querySelectorAll('video');
                        if (videos.length === 0) return true;
                        
                        // Wait for at least one video to be playing or loaded
                        return Array.from(videos).some(video => {
                            return !video.paused || video.readyState >= 2; // HAVE_CURRENT_DATA
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
                        const videos = document.querySelectorAll('video');
                        if (videos.length === 0) return true;
                        return Array.from(videos).some(video => video.readyState >= 2);
                    }
                    """,
                    {"timeout": 5000},
                )

        except Exception as e:
            console.log(f"Video handling failed: {e}")
            # Fallback to simple wait
            if timeout_ms:
                await asyncio.sleep(timeout_ms / 1000)
            else:
                await asyncio.sleep(2)

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
    )

    output = "/tmp/" + imgname.replace(format, "png")
    output_final = "/tmp/" + imgname

    # Check if exists in S3
    if config.s3_client.file_exists(imgname):
        return imgname, output_final, True  # exists in S3

    # Take screenshot
    screenshot_success = await take_screenshot(
        url, width, height, selector_list, output, timeout_ms
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
