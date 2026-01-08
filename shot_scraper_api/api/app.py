import asyncio
import hashlib
import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from fastapi import FastAPI, HTTPException, Request, Response
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


async def generate_image_data(
    url: str,
    width: int,
    height: int,
    selector_list: list,
    format: str,
    scaled_width: int,
    scaled_height: int,
):
    """Generate image and return file path and format"""
    # Generate unique filename
    imgname = (
        hashlib.md5(f"{url}{''.join(selector_list)}".encode()).hexdigest()
        + f"-{width}x{height}-{scaled_width}x{scaled_height}.{format}"
    ).lower()

    output = "/tmp/" + imgname.replace(format, "png")
    output_final = "/tmp/" + imgname

    # Check if exists in S3
    if config.s3_client.file_exists(imgname):
        return imgname, output_final, True  # exists in S3

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

    # Upload to S3
    if Path(output_final).exists():
        print("putting", output_final, imgname)
        await config.s3_client.upload_file(output_final, imgname)

    return imgname, output_final, False  # newly created


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


@app.api_route("/shot/", methods=["GET", "HEAD"])
@app.api_route("/shot", methods=["GET", "HEAD"])
@app.api_route("/shot/{filename}", methods=["GET", "HEAD"])
@app.api_route("/shot/{filename}/", methods=["GET", "HEAD"])
async def get_shot(
    request: Request,
    url: str,
    filename: Optional[str] = "screenshot.webp",
    height: Optional[int] = 450,
    width: Optional[int] = 800,
    scaled_height: Optional[int | str] = None,
    scaled_width: Optional[int | str] = None,
    selectors: Optional[str] = None,
    format: Optional[str] = None,
):
    # Determine format from query parameter or filename extension
    if format:
        format = format.lower()
        if format not in ["webp", "png", "jpg", "jpeg"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid format. Must be one of: webp, png, jpg/jpeg",
            )
    else:
        ext = (
            filename.split(".")[-1].lower() if filename and "." in filename else "webp"
        )
        if ext not in ["webp", "png", "jpg", "jpeg"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid format. Must be one of: webp, png, jpg/jpeg",
            )
        format = "jpg" if ext == "jpeg" else ext

    scaled_height = int(scaled_height) if scaled_height else height
    scaled_width = int(scaled_width) if scaled_width else width

    # Ensure width and height are not None for take_screenshot
    width = width or 800
    height = height or 450
    selector_list = selectors.split(",") if selectors else []

    # Ensure scaled dimensions are integers (not None)
    scaled_height = int(scaled_height) if scaled_height else height
    scaled_width = int(scaled_width) if scaled_width else width

    if not url.startswith("http"):
        raise HTTPException(status_code=404, detail="url is not a url")

    # Handle HTMX requests (only for GET)
    hx_request_header = request.headers.get("hx-request")
    if hx_request_header and request.method == "GET":
        imgname = (
            hashlib.md5(f"{url}{''.join(selector_list)}".encode()).hexdigest()
            + f"-{width}x{height}-{scaled_width}x{scaled_height}.{format}"
        ).lower()
        print(
            f"height: {height}, width: {width}, scaled_height: {scaled_height}, scaled_width: {scaled_width}, imgname: {imgname}"
        )
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

    # Generate or get image data
    imgname, output_path, exists_in_s3 = await generate_image_data(
        url, width, height, selector_list, format, scaled_width, scaled_height
    )

    # Get image data from S3
    imgdata = await config.s3_client.get_file(imgname)
    print("streaming from minio")

    # Handle HEAD requests - read all data to determine content-length
    if request.method == "HEAD":
        # Read all chunks to calculate total size
        chunks = []
        total_size = 0
        async for chunk in imgdata:
            chunks.append(chunk)
            total_size += len(chunk)

        # Create headers for HEAD response
        headers = {
            "Cache-Control": "public, max-age=86400",
            "Content-Type": f"image/{format}",
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
            "Content-Length": str(total_size),
        }

        return Response(headers=headers, status_code=200)

    # For GET requests, stream the image data
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
