import asyncio
import hashlib
import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pyppeteer import launch

from shot_scraper_api.config import config
from shot_scraper_api.console import console


app = FastAPI()


@app.on_event("startup")
async def startup_event():
    """Initialize and warm up the browser"""
    try:
        console.log("Browser initialized and warmed up")
    except Exception as e:
        console.log(f"Failed to initialize browser: {str(e)}")


@app.on_event("shutdown")
async def shutdown_event():
    pass


async def take_screenshot(
    url: str, width: int, height: int, selector_list: list, output: str
):
    """Take a screenshot of a webpage"""
    try:
        # Launch browser
        browser = await launch(args=["--no-sandbox"])
        page = await browser.newPage()

        # Set viewport
        await page.setViewport({"width": width, "height": height})

        # Navigate to URL
        await page.goto(url, {"waitUntil": "networkidle0", "timeout": 30000})

        # Wait for selectors if specified
        for selector in selector_list:
            try:
                await page.waitForSelector(selector, {"timeout": 5000})
            except:
                console.log(f"Selector {selector} not found")

        # Take screenshot
        await page.screenshot({"path": output, "fullPage": False})
        await browser.close()
        return True
    except Exception as e:
        console.log(f"Screenshot failed: {str(e)}")
        return False


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
    print(
        f"height: {height}, width: {width}, scaled_height: {scaled_height}, scaled_width: {scaled_width}, imgname: {imgname}"
    )
    if hx_request_header:
        return templates.TemplateResponse(
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

    output = "/tmp/" + imgname.replace(format, "png")
    output_final = "/tmp/" + imgname

    if config.s3_client.file_exists(imgname):
        # print(f"getting presigned url for {imgname} from minio")
        # imgdata = config.minio_client.get_object(config.bucket_name, imgname)
        imgdata = await config.s3_client.get_file(imgname)
        print("streaming from minio")

        return StreamingResponse(
            imgdata,
            media_type=f"image/{format}",
            headers={
                "Cache-Control": "public, max-age=86400",
                "Content-Type": f"image/{format}",
                "Access-Control-Allow-Origin": "*",
                "Cross-Origin-Resource-Policy": "cross-origin",
            },
        )

        # url = await config.s3_client.get_file_url(imgname)
        #
        # # url = "https://minio.wayl.one/shots-dev/8677021b0cb2a77677d6cd1da039623f-800x450-800x450.webp?AWSAccessKeyId=DSg2xoicDrBGbJoLrCuj&Signature=%2F3DVDvDDxL83QKn7erZ%2BfD8%2FIb4%3D&Expires=1737057467"
        # print(f"got presigned url: {url}")
        # return RedirectResponse(
        #     url=url,
        #     status_code=307,  # Temporary redirect
        #     headers={
        #         "Cache-Control": "public, max-age=86400",
        #         "Content-Type": f"image/{format}",
        #         "Access-Control-Allow-Origin": "*",
        #         "Cross-Origin-Resource-Policy": "cross-origin",
        #     },
        # )

    # Take screenshot
    screenshot_success = await take_screenshot(
        url, width, height, selector_list, output
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

    # url = await config.s3_client.get_file_url(imgname)
    # print(f"got presigned url: {url}")
    # return RedirectResponse(
    #     url=url,
    #     status_code=307,  # Temporary redirect
    #     headers={
    #         "Cache-Control": "public, max-age=86400",
    #         "Content-Type": f"image/{format}",
    #         "Access-Control-Allow-Origin": "*",
    #         "Cross-Origin-Resource-Policy": "cross-origin",
    #     },
    # )
    return StreamingResponse(
        content=imgdata,
        media_type=f"image/{format}",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Type": f"image/{format}",
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
        },
    )
