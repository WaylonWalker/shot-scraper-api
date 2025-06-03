import asyncio
import hashlib
import os
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pyppeteer import launch
import pydantic
import uuid
from pydantic import BaseModel, field_validator, ValidationInfo

from shot_scraper_api.config import config
from shot_scraper_api.console import console

import redis.asyncio as aioredis

redis = aioredis.from_url(
    "redis://localhost:6379", encoding="utf-8", decode_responses=True
)


app = FastAPI()

SHOT_QUEUE = {}


class Screenshot(BaseModel):
    job_id: uuid.UUID = pydantic.Field(default_factory=uuid.uuid4)
    url: str
    width: int
    height: int
    output: str
    output_final: str
    selector_list: list[str] = []
    s3_key: str | None = None
    scaled_width: Optional[int] = None
    scaled_height: Optional[int] = None

    @property
    def needs_scaling(self) -> bool:
        """Check if image needs to be scaled."""
        return (
            self.scaled_width is not None
            and self.scaled_height is not None
            and (self.scaled_width != self.width or self.scaled_height != self.height)
        )

    @field_validator("scaled_width", "scaled_height", mode="before")
    @classmethod
    def set_scaled_dimensions(
        cls, v: Optional[int], info: ValidationInfo
    ) -> Optional[int]:
        """Set scaled dimensions if not provided, maintaining aspect ratio."""
        values = info.data
        if "width" not in values or "height" not in values:
            return v

        original_width = values["width"]
        original_height = values["height"]

        # If neither scaled dimension is provided, use original dimensions
        if values.get("scaled_width") is None and values.get("scaled_height") is None:
            if info.field_name == "scaled_width":
                return original_width
            return original_height

        # If one scaled dimension is provided, calculate the other maintaining aspect ratio
        if (
            info.field_name == "scaled_width"
            and v is None
            and values.get("scaled_height")
        ):
            scaled_height = values["scaled_height"]
            return int(original_width * (scaled_height / original_height))
        elif (
            info.field_name == "scaled_height"
            and v is None
            and values.get("scaled_width")
        ):
            scaled_width = values["scaled_width"]
            return int(original_height * (scaled_width / original_width))

        return v


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


@app.get("/raw_queue")
async def get_queue():
    # return SHOT_QUEUE
    raw_jobs = await redis.lrange("job_queue", 0, -1)
    return {"pending_jobs": raw_jobs}
    # parse each JSON blob into a dict


@app.get("/queue")
async def get_queue():
    import json

    raw_jobs = await redis.lrange("job_queue", 0, -1)
    jobs = [Screenshot.model_validate(json.loads(job)) for job in raw_jobs]
    return {"pending_jobs": jobs}


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
    scaled_height = int(scaled_height) if scaled_height else height
    scaled_width = int(scaled_width) if scaled_width else width
    output: Path = Path("screenshots")
    safe_filename = url.replace("https://", "").replace("http://", "").replace("/", "_")
    screenshot = Screenshot(
        url=url,
        width=width,
        height=height,
        scaled_width=scaled_width,
        scaled_height=scaled_height,
        selector_list=selectors.split(",") if selectors else [],
        output=str(output / f"{safe_filename}.png"),
        output_final=str(output / f"{safe_filename}.png"),
    )

    await redis.rpush("job_queue", screenshot.model_dump_json())
    return {"job_id": screenshot.job_id}
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
        print("HTMX request")
        imgname = (
            hashlib.md5(f"{url}{''.join(selector_list)}".encode()).hexdigest()
            + f"-{width}x{height}-{scaled_width}x{scaled_height}.{format}"
        ).lower()

        # Check if image exists
        if config.s3_client.file_exists(imgname):
            # Image is ready, return the image URL
            return templates.TemplateResponse(
                "image_status.html",
                {
                    "request": request,
                    "image_ready": True,
                    "image_url": f"/shot/?url={quote_plus(url)}&width={width}&height={height}&scaled_width={scaled_width}&scaled_height={scaled_height}&selectors={selectors}",
                    "scaled_width": scaled_width,
                    "scaled_height": scaled_height,
                },
            )
        else:
            # Image not ready, return loading template
            output = "/tmp/" + imgname.replace(format, "png")
            output_final = "/tmp/" + imgname
            SHOT_QUEUE[imgname] = {
                "url": url,
                "width": width,
                "height": height,
                "scaled_height": scaled_height,
                "scaled_width": scaled_width,
                "selector_list": selector_list,
                "output": output,
                "output_final": output_final,
                "format": format,
            }
            return templates.TemplateResponse(
                "image_status.html",
                {
                    "request": request,
                    "image_ready": False,
                    "image_url": "",
                    "scaled_width": scaled_width,
                    "scaled_height": scaled_height,
                },
            )
    else:
        print("Non-HTMX request")
        output = "/tmp/" + imgname.replace(format, "png")
        output_final = "/tmp/" + imgname

        if config.s3_client.file_exists(imgname):
            file = await config.s3_client.get_file(imgname)

            async def iterfile():
                yield file

            return StreamingResponse(
                iterfile(),
                media_type=f"image/{format}",
            )

        SHOT_QUEUE[imgname] = {
            "url": url,
            "width": width,
            "height": height,
            "scaled_height": scaled_height,
            "scaled_width": scaled_width,
            "selector_list": selector_list,
            "output": output,
            "output_final": output_final,
            "format": format,
        }

        return StreamingResponse(
            iterfile(),
            media_type=f"image/{format}",
        )

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

    url = await config.s3_client.get_file_url(imgname)
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
