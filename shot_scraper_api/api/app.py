import os
from typing import Optional
from urllib.parse import quote_plus

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from shot_scraper_api.config import config
from shot_scraper_api.console import console
from shot_scraper_api.processor import start_queue_processor, stop_queue_processor
from shot_scraper_api.queue import get_queue
from shot_scraper_api.screenshot import build_image_name


app = FastAPI()


@app.on_event("startup")
async def startup_event():
    """Initialize and warm up the browser"""
    try:
        if config.queue_processor_enabled:
            # Start the queue processor
            await start_queue_processor()
            console.log("Queue processor started")
        else:
            console.log("Queue processor disabled")

        console.log("Browser initialized and warmed up")
    except Exception as e:
        console.log(f"Failed to initialize browser: {str(e)}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    try:
        if config.queue_processor_enabled:
            await stop_queue_processor()
            console.log("Queue processor stopped")
    except Exception as e:
        console.log(f"Error during shutdown: {str(e)}")


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


@app.post("/trigger/shot")
async def trigger_shot(
    request: Request,
    url: str = Query(...),
    width: int = Query(default=800),
    height: int = Query(default=450),
    scaled_width: Optional[int] = Query(default=None),
    scaled_height: Optional[int] = Query(default=None),
    selectors: Optional[str] = Query(default=None),
    format: Optional[str] = Query(default="webp"),
    v: Optional[str] = Query(default=None),
    timeout: Optional[str] = Query(default=None),
    priority: int = Query(default=0),
):
    """Trigger a screenshot job for build processes"""
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="url is not a url")

    if format not in ["webp", "png", "jpg", "jpeg"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid format. Must be one of: webp, png, jpg/jpeg",
        )
    if format == "jpeg":
        format = "jpg"

    # Parse version parameter
    version = None
    if v is not None and v.strip():
        try:
            version = int(v)
            if version <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Version must be a positive integer (v=1, v=2, etc.)",
                )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Version must be a valid integer (v=1, v=2, etc.)",
            )

    # Parse timeout parameter
    timeout_ms = None
    if timeout is not None and timeout.strip():
        try:
            timeout_ms = int(timeout)
            if timeout_ms <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Timeout must be a positive integer in milliseconds",
                )
            if timeout_ms > 60000:
                raise HTTPException(
                    status_code=400,
                    detail="Timeout cannot exceed 60000 milliseconds (60 seconds)",
                )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Timeout must be a valid integer in milliseconds",
            )

    # Validate priority
    if not (0 <= priority <= 10):
        raise HTTPException(
            status_code=400,
            detail="Priority must be between 0 (low) and 10 (high)",
        )

    # Check if already exists in S3
    selector_list = selectors.split(",") if selectors else []
    imgname = build_image_name(
        url,
        selector_list,
        width,
        height,
        scaled_width or width,
        scaled_height or height,
        format,
        version,
    )

    # Check if already queued or processing
    queue = get_queue()
    if queue.is_shot_queued_or_processing(
        url,
        width,
        height,
        selectors,
        version,
        scaled_width,
        scaled_height,
        format,
    ):
        job_id = queue.get_job_id_by_filename(imgname)
        return JSONResponse(
            {
                "status": "already_queued",
                "job_id": job_id,
                "filename": imgname,
                "job_url": f"/job/{job_id}" if job_id else None,
                "result_url": f"/shot/{imgname}",
                "message": "Screenshot with these parameters is already queued or processing",
            }
        )

    if config.s3_client.file_exists(imgname):
        return JSONResponse(
            {
                "status": "exists",
                "message": "Screenshot already exists",
                "filename": imgname,
            }
        )

    # Add to queue
    job_id = queue.add_job(
        url=url,
        width=width,
        height=height,
        selectors=selectors,
        format=format,
        scaled_width=scaled_width,
        scaled_height=scaled_height,
        version=version,
        timeout=timeout_ms,
        priority=priority,
    )

    console.log(f"Queued screenshot job {job_id} for {url}")

    return JSONResponse(
        {
            "status": "queued",
            "job_id": job_id,
            "filename": imgname,
            "job_url": f"/job/{job_id}",
            "result_url": f"/shot/{imgname}",
            "message": "Screenshot queued for processing",
        }
    )


@app.get("/job/{job_id}")
async def get_job_status(job_id: str):
    """Get status of a specific job"""
    queue = get_queue()
    job_data = queue.get_job(job_id)

    if not job_data:
        raise HTTPException(status_code=404, detail="Job not found")

    return JSONResponse(job_data)


@app.get("/queue/stats")
async def get_queue_stats():
    """Get queue statistics"""
    queue = get_queue()
    stats = queue.get_queue_stats()
    return JSONResponse(stats)


@app.api_route("/shot/", methods=["GET", "HEAD"])
@app.api_route("/shot", methods=["GET", "HEAD"])
@app.api_route("/shot/{filename}", methods=["GET", "HEAD"])
@app.api_route("/shot/{filename}/", methods=["GET", "HEAD"])
async def get_shot(
    request: Request,
    url: Optional[str] = None,
    filename: Optional[str] = None,
    height: Optional[int] = 450,
    width: Optional[int] = 800,
    scaled_height: Optional[int | str] = None,
    scaled_width: Optional[int | str] = None,
    selectors: Optional[str] = None,
    format: Optional[str] = None,
    v: Optional[str] = Query(default=None),
    timeout: Optional[str] = Query(default=None),
):
    # Determine format from query parameter or filename extension
    if format:
        format = format.lower()
        if format not in ["webp", "png", "jpg", "jpeg"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid format. Must be one of: webp, png, jpg/jpeg",
            )
        if format == "jpeg":
            format = "jpg"
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

    if url is None:
        if not filename:
            raise HTTPException(status_code=400, detail="url is required")

        imgdata = await config.s3_client.get_file(filename)
        if request.method == "HEAD":
            headers = {
                "Cache-Control": "public, max-age=86400",
                "Content-Type": f"image/{format}",
                "Access-Control-Allow-Origin": "*",
                "Cross-Origin-Resource-Policy": "cross-origin",
                "X-Screenshot-Status": "ready",
            }
            return Response(headers=headers, status_code=200)

        return StreamingResponse(
            content=imgdata,
            media_type=f"image/{format}",
            headers={
                "Cache-Control": "public, max-age=86400",
                "Content-Type": f"image/{format}",
                "Access-Control-Allow-Origin": "*",
                "Cross-Origin-Resource-Policy": "cross-origin",
                "X-Screenshot-Status": "ready",
            },
        )

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

    # Parse and validate version parameter
    version = None
    if v is not None and v.strip():  # Check if v is not empty string
        try:
            version = int(v)
            if version <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Version must be a positive integer (v=1, v=2, etc.)",
                )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Version must be a valid integer (v=1, v=2, etc.)",
            )

    # Parse and validate timeout parameter
    timeout_ms = None
    if timeout is not None and timeout.strip():  # Check if timeout is not empty string
        try:
            timeout_ms = int(timeout)
            if timeout_ms <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Timeout must be a positive integer in milliseconds (e.g., 5000 for 5 seconds)",
                )
            if timeout_ms > 60000:  # 60 second maximum
                raise HTTPException(
                    status_code=400,
                    detail="Timeout cannot exceed 60000 milliseconds (60 seconds)",
                )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Timeout must be a valid integer in milliseconds (e.g., 5000 for 5 seconds)",
            )

    # Handle HTMX requests (only for GET)
    hx_request_header = request.headers.get("hx-request")
    if hx_request_header and request.method == "GET":
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
        print(
            f"height: {height}, width: {width}, scaled_height: {scaled_height}, scaled_width: {scaled_width}, imgname: {imgname}"
        )
        queue = get_queue()
        job_id = queue.get_job_id_by_filename(imgname)
        status = "processing"
        if config.s3_client.file_exists(imgname):
            status = "exists"
        else:
            if not job_id:
                job_id = queue.add_job(
                    url=url,
                    width=width,
                    height=height,
                    selectors=selectors,
                    format=format,
                    scaled_width=scaled_width,
                    scaled_height=scaled_height,
                    version=version,
                    timeout=timeout_ms,
                    priority=0,
                )
                status = "queued"
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
                "format": format,
                "v": v,
                "timeout": timeout,
                "job_id": job_id,
                "status": status,
            },
        )

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

    if config.s3_client.file_exists(imgname):
        if request.method == "HEAD":
            headers = {
                "Cache-Control": "public, max-age=86400",
                "Content-Type": f"image/{format}",
                "Access-Control-Allow-Origin": "*",
                "Cross-Origin-Resource-Policy": "cross-origin",
                "X-Screenshot-Status": "ready",
            }
            return Response(headers=headers, status_code=200)

        return JSONResponse(
            {
                "status": "exists",
                "filename": imgname,
                "result_url": f"/shot/{imgname}",
            },
            status_code=200,
        )

    # Check if shot is already queued or processing
    queue = get_queue()
    if queue.is_shot_queued_or_processing(
        url,
        width,
        height,
        selectors,
        version,
        scaled_width,
        scaled_height,
        format,
    ):
        job_id = queue.get_job_id_by_filename(imgname)
        if request.method == "HEAD":
            # Return headers indicating shot is being processed
            headers = {
                "Cache-Control": "no-cache",
                "Content-Type": f"image/{format}",
                "Access-Control-Allow-Origin": "*",
                "Cross-Origin-Resource-Policy": "cross-origin",
                "X-Screenshot-Status": "processing",
                "X-Job-Id": job_id or "",
            }
            return Response(headers=headers, status_code=202)  # Accepted
        else:
            return JSONResponse(
                {
                    "status": "processing",
                    "job_id": job_id,
                    "filename": imgname,
                    "result_url": f"/shot/{imgname}",
                },
                status_code=202,
            )

    job_id = queue.add_job(
        url=url,
        width=width,
        height=height,
        selectors=selectors,
        format=format,
        scaled_width=scaled_width,
        scaled_height=scaled_height,
        version=version,
        timeout=timeout_ms,
        priority=0,
    )

    if request.method == "HEAD":
        headers = {
            "Cache-Control": "no-cache",
            "Content-Type": f"image/{format}",
            "Access-Control-Allow-Origin": "*",
            "Cross-Origin-Resource-Policy": "cross-origin",
            "X-Screenshot-Status": "queued",
            "X-Job-Id": job_id,
        }
        return Response(headers=headers, status_code=202)

    return JSONResponse(
        {
            "status": "queued",
            "job_id": job_id,
            "filename": imgname,
            "job_url": f"/job/{job_id}",
            "result_url": f"/shot/{imgname}",
            "message": "Screenshot queued for processing",
        },
        status_code=202,
    )
