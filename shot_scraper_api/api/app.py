import asyncio
import hashlib
import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright

from shot_scraper_api.config import config
from shot_scraper_api.console import console


# Browser configuration
class BrowserPool:
    def __init__(self, max_browsers=2):
        self.max_browsers = max_browsers
        self.browsers = []
        self.lock = asyncio.Lock()
        self.playwright = None
        self._ready = asyncio.Event()

    async def start(self):
        """Initialize playwright and warm up the browser pool"""
        if not self.playwright:
            self.playwright = await async_playwright().start()

            # Pre-launch browsers up to max_browsers
            async with self.lock:
                for _ in range(self.max_browsers):
                    try:
                        browser = await self.playwright.chromium.launch(
                            args=[
                                "--disable-dev-shm-usage",
                                "--disable-accelerated-2d-canvas",
                                "--disable-gpu",
                                "--disable-extensions",
                                "--disable-background-networking",
                                "--disable-background-timer-throttling",
                                "--disable-backgrounding-occluded-windows",
                                "--disable-breakpad",
                                "--disable-client-side-phishing-detection",
                                "--disable-component-extensions-with-background-pages",
                                "--disable-default-apps",
                                "--disable-features=TranslateUI,BlinkGenPropertyTrees",
                                "--disable-hang-monitor",
                                "--disable-ipc-flooding-protection",
                                "--disable-popup-blocking",
                                "--disable-prompt-on-repost",
                                "--disable-renderer-backgrounding",
                                "--disable-sync",
                                "--force-color-profile=srgb",
                                "--metrics-recording-only",
                                "--no-first-run",
                                "--enable-automation",
                                "--password-store=basic",
                                "--use-mock-keychain",
                            ]
                        )
                        browser_info = {
                            "browser": browser,
                            "in_use": False,
                            "closed": False,
                            "context": await browser.new_context(
                                viewport={"width": 1920, "height": 1080},
                                java_script_enabled=True,
                                bypass_csp=True,
                                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                            ),
                        }
                        self.browsers.append(browser_info)
                    except Exception as e:
                        console.log(f"Failed to launch browser during warmup: {str(e)}")

            # Signal that the pool is ready
            self._ready.set()

    async def ensure_ready(self):
        """Wait for the browser pool to be ready"""
        await self._ready.wait()

    async def get_browser(self):
        # Ensure pool is initialized
        if not self._ready.is_set():
            await self.start()
        await self.ensure_ready()

        async with self.lock:
            # Clean up crashed browsers
            self.browsers = [b for b in self.browsers if not b.get("closed", True)]

            # Try to find an available browser
            for browser_info in self.browsers:
                if not browser_info["in_use"]:
                    browser_info["in_use"] = True
                    return browser_info

            # If no browsers available and under limit, create new one
            if len(self.browsers) < self.max_browsers:
                try:
                    browser = await self.playwright.chromium.launch(
                        args=[
                            "--disable-dev-shm-usage",
                            "--disable-accelerated-2d-canvas",
                            "--disable-gpu",
                            "--disable-extensions",
                            "--disable-background-networking",
                            "--disable-background-timer-throttling",
                            "--disable-backgrounding-occluded-windows",
                            "--disable-breakpad",
                            "--disable-client-side-phishing-detection",
                            "--disable-component-extensions-with-background-pages",
                            "--disable-default-apps",
                            "--disable-features=TranslateUI,BlinkGenPropertyTrees",
                            "--disable-hang-monitor",
                            "--disable-ipc-flooding-protection",
                            "--disable-popup-blocking",
                            "--disable-prompt-on-repost",
                            "--disable-renderer-backgrounding",
                            "--disable-sync",
                            "--force-color-profile=srgb",
                            "--metrics-recording-only",
                            "--no-first-run",
                            "--enable-automation",
                            "--password-store=basic",
                            "--use-mock-keychain",
                        ]
                    )
                    browser_info = {
                        "browser": browser,
                        "in_use": True,
                        "closed": False,
                        "context": await browser.new_context(
                            viewport={"width": 1920, "height": 1080},
                            java_script_enabled=True,
                            bypass_csp=True,
                            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        ),
                    }
                    self.browsers.append(browser_info)
                    return browser_info
                except Exception as e:
                    console.log(f"Failed to launch browser: {str(e)}")
                    raise HTTPException(
                        status_code=500, detail="Failed to launch browser"
                    )

            # Wait for an available browser
            while True:
                for browser_info in self.browsers:
                    if not browser_info["in_use"]:
                        browser_info["in_use"] = True
                        return browser_info
                await asyncio.sleep(0.1)

    async def release_browser(self, browser_info):
        async with self.lock:
            if browser_info in self.browsers:
                browser_info["in_use"] = False

    async def cleanup(self):
        async with self.lock:
            for browser_info in self.browsers:
                try:
                    if not browser_info["closed"]:
                        await browser_info["browser"].close()
                        browser_info["closed"] = True
                except:
                    pass
            self.browsers = []
            if self.playwright:
                await self.playwright.stop()
                self.playwright = None


# Global browser pool
browser_pool = BrowserPool(max_browsers=2)

app = FastAPI()


@app.on_event("startup")
async def startup_event():
    """Initialize and warm up the browser pool during startup"""
    try:
        await browser_pool.start()
        console.log("Browser pool initialized and warmed up")
    except Exception as e:
        console.log(f"Failed to initialize browser pool: {str(e)}")


@app.on_event("shutdown")
async def shutdown_event():
    await browser_pool.cleanup()


async def take_screenshot(
    url: str,
    width: int,
    height: int,
    selector_list: list,
    output: str,
    sleep_time: int = 0,
):
    # Ensure browser pool is ready before proceeding
    await browser_pool.ensure_ready()

    browser_info = None
    try:
        browser_info = await browser_pool.get_browser()
        context = browser_info["context"]

        # Create new page with optimized settings
        page = await context.new_page()

        try:
            # Set viewport if different from default
            if width != 1920 or height != 1080:
                await page.set_viewport_size({"width": width, "height": height})

            # Navigate with optimized settings
            response = await page.goto(
                url, wait_until="domcontentloaded", timeout=15000
            )

            if not response or not response.ok:
                raise HTTPException(
                    status_code=response.status if response else 500,
                    detail=f"Failed to load page: {response.status if response else 'Unknown error'}",
                )

            # Wait for full page load first
            try:
                await page.wait_for_load_state("load", timeout=5000)
            except:
                # Continue even if full load times out
                pass

            # Wait for network to be idle for a short time
            try:
                await page.wait_for_load_state("networkidle", timeout=2000)
            except:
                # Continue even if network doesn't become fully idle
                pass

            # Additional manual sleep time if specified
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
            else:
                # Default small delay to allow initial animations to settle
                await asyncio.sleep(1)

            # Wait for selectors if specified
            if selector_list:
                for selector in selector_list:
                    try:
                        await page.wait_for_selector(selector, timeout=2000)
                    except Exception as e:
                        console.log(f"Selector {selector} not found: {str(e)}")

            # Take screenshot with optimized settings
            await page.screenshot(
                path=output,
                type="jpeg",
                quality=80,
                animations="disabled",
                scale="device",
            )
            return True

        finally:
            await page.close()

    except Exception as e:
        console.log(f"Screenshot failed: {str(e)}")
        if browser_info:
            browser_info["closed"] = True
            try:
                await browser_info["browser"].close()
            except:
                pass
        raise HTTPException(
            status_code=500, detail=f"Failed to take screenshot: {str(e)}"
        )

    finally:
        if browser_info:
            await browser_pool.release_browser(browser_info)


app.mount("/static", StaticFiles(directory="static"), name="static")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

templates = Jinja2Templates(directory="templates")

# ENV = os.environ["ENV"]
# ACCESS_KEY = os.environ.get("ACCESS_KEY", "").strip("\n")
# SECRET_KEY = os.environ.get("SECRET_KEY", "").strip("\n")
# SECRET_KEY = os.environ.get("BUCKET_NAME", "shots").strip("\n")


if config.env == "dev":
    import arel

    hot_reload = arel.HotReload(
        paths=[
            arel.Path("static"),
            arel.Path("templates"),
            arel.Path("shot_scraper_api"),
        ],
    )
    app.add_websocket_route("/hot-reload", route=hot_reload, name="hot-reload")
    app.add_event_handler("startup", hot_reload.startup)
    app.add_event_handler("shutdown", hot_reload.shutdown)
    templates.env.globals["DEBUG"] = True
    templates.env.globals["hot_reload"] = hot_reload

templates.env.filters["quote_plus"] = lambda u: quote_plus(str(u))


@app.get("/")
def get(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "env": os.environ,
        },
    )


@app.get("/favicon.ico", response_class=FileResponse)
async def get_favicon(request: Request):
    output = "static/8bitcc.ico"
    return FileResponse(output)


@app.get(
    "/shot/",
    # responses={200: {"content": {"image/webp": {}, "image/png": {}, "image/jpeg": {}}}},
)
@app.get(
    "/shot",
    # responses={200: {"content": {"image/webp": {}, "image/png": {}, "image/jpeg": {}}}},
)
@app.get(
    "/shot/{filename}",
    # responses={200: {"content": {"image/webp": {}, "image/png": {}, "image/jpeg": {}}}},
)
@app.get(
    "/shot/{filename}/",
    # responses={200: {"content": {"image/webp": {}, "image/png": {}, "image/jpeg": {}}}},
)
async def get_shot(
    request: Request,
    url: str,
    filename: Optional[str] = "screenshot.webp",
    height: Optional[int] = 450,
    width: Optional[int] = 800,
    scaled_height: Optional[int | str] = None,
    scaled_width: Optional[int | str] = None,
    selectors: Optional[str] = None,
):
    # Get format from filename extension
    ext = filename.split(".")[-1].lower() if "." in filename else "webp"
    if ext not in ["webp", "png", "jpg", "jpeg"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid format. Must be one of: webp, png, jpg/jpeg",
        )

    # Normalize jpeg to jpg
    format = "jpg" if ext == "jpeg" else ext

    scaled_height = int(scaled_height) if scaled_height else height
    scaled_width = int(scaled_width) if scaled_width else width
    selector_list = selectors.split(",") if selectors else []

    if not url.startswith("http"):
        raise HTTPException(status_code=404, detail="url is not a url")

    hx_request_header = request.headers.get("hx-request")
    imgname = (
        hashlib.md5(f"{url}{''.join(selector_list)}".encode()).hexdigest()
        + f"-{width}x{height}-{scaled_width}x{scaled_height}.{format}"
    ).lower()
    print(f'getting image for url "{url}"')
    print(
        f"height: {height}, width: {width}, scaled_height: {scaled_height}, scaled_width: {scaled_width}, imgname: {imgname}"
    )
    if hx_request_header:
        print(f'returning image template for url "{url}"')
        response = templates.TemplateResponse(
            "output.html",
            {
                "request": request,
                "imgname": imgname,
                "url": url,
                "height": height,
                "width": width,
                "scaled_height": scaled_height,
                "scaled_width": scaled_width,
                "selectors": selectors,
            },
        )
        return response

    output = "/tmp/" + imgname.replace(format, "png")
    output_final = "/tmp/" + imgname

    if config.s3_client.file_exists(imgname):
        print(f"getting presigned url for {imgname} from minio")
        # imgdata = config.minio_client.get_object(config.bucket_name, imgname)
        # print("streaming from minio")

        url = await config.s3_client.get_file_url(imgname)

        # url = "https://minio.wayl.one/shots-dev/8677021b0cb2a77677d6cd1da039623f-800x450-800x450.webp?AWSAccessKeyId=DSg2xoicDrBGbJoLrCuj&Signature=%2F3DVDvDDxL83QKn7erZ%2BfD8%2FIb4%3D&Expires=1737057467"
        print(f"got presigned url: {url}")
        return RedirectResponse(
            url=url,
            status_code=307,  # Temporary redirect
            headers={
                "Cache-Control": "public, max-age=86400",
                "Content-Type": f"image/{format}",
                "Access-Control-Allow-Origin": "*",
                "Cross-Origin-Resource-Policy": "cross-origin",
            },
        )

        # return StreamingResponse(
        #     content=imgdata,
        #     media_type=f"image/{format}",
        #     headers={
        #         "Cache-Control": "public, max-age=86400",
        #         "Content-Type": f"image/{format}",
        #         "Access-Control-Allow-Origin": "*",
        #         "Cross-Origin-Resource-Policy": "cross-origin",
        #     },
        # )

    print(f'taking screenshot for "{url}"')
    success = await take_screenshot(url, width, height, selector_list, output)
    if not success:
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

    if Path(output_final).exists():
        print("putting", output_final, imgname)
        await config.s3_client.upload_file(output_final, imgname)
        # config.minio_client.fput_object(
        #     config.bucket_name,
        #     imgname,
        #     output_final,
        # )

        # imgdata = config.minio_client.get_object(config.bucket_name, imgname)
        # print("streaming from minio")

    url = await config.s3_client.get_file_url(imgname)
    print(f"got presigned url: {url}")
    return RedirectResponse(
        url=url,
        status_code=307,  # Temporary redirect
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Type": f"image/{format}",
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )
    # return StreamingResponse(
    #     content=imgdata,
    #     media_type=f"image/{format}",
    #     headers={
    #         "Cache-Control": "public, max-age=86400",
    #         "Content-Type": f"image/{format}",
    #         "Access-Control-Allow-Origin": "*",
    #         "Cross-Origin-Resource-Policy": "cross-origin",
    #     },
    # )
