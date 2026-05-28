import asyncio
import os
import time
from typing import Dict, Optional
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
from shot_scraper_api.screenshot import build_image_name, close_browser, warm_browser


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

        await warm_browser()
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
        await close_browser()
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


def _normalize_format(format: Optional[str], filename: Optional[str] = None) -> str:
    """Normalize requested screenshot format."""
    if format:
        normalized_format = format.lower()
        if normalized_format not in ["webp", "png", "jpg", "jpeg"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid format. Must be one of: webp, png, jpg/jpeg",
            )
        return "jpg" if normalized_format == "jpeg" else normalized_format

    ext = filename.split(".")[-1].lower() if filename and "." in filename else "webp"
    if ext not in ["webp", "png", "jpg", "jpeg"]:
        raise HTTPException(
            status_code=400,
            detail="Invalid format. Must be one of: webp, png, jpg/jpeg",
        )
    return "jpg" if ext == "jpeg" else ext


def _parse_version(v: Optional[str]) -> Optional[int]:
    """Parse and validate version query parameter."""
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
    return version


def _parse_timeout(timeout: Optional[str]) -> Optional[int]:
    """Parse and validate screenshot timeout in milliseconds."""
    timeout_ms = None
    if timeout is not None and timeout.strip():
        try:
            timeout_ms = int(timeout)
            if timeout_ms <= 0:
                raise HTTPException(
                    status_code=400,
                    detail="Timeout must be a positive integer in milliseconds (e.g., 5000 for 5 seconds)",
                )
            if timeout_ms > 60000:
                raise HTTPException(
                    status_code=400,
                    detail="Timeout cannot exceed 60000 milliseconds (60 seconds)",
                )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Timeout must be a valid integer in milliseconds (e.g., 5000 for 5 seconds)",
            )
    return timeout_ms


def _parse_theme(theme: Optional[str]) -> Optional[str]:
    """Parse and validate screenshot theme preference."""
    if theme is None:
        return None

    normalized_theme = theme.strip().lower()
    if not normalized_theme:
        return None

    if normalized_theme not in ["light", "dark"]:
        raise HTTPException(
            status_code=400,
            detail="theme must be one of: light, dark",
        )

    return normalized_theme


def _format_to_media_type(format: str) -> str:
    """Map format string to correct media type."""
    return {"jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(format, f"image/{format}")


def _image_headers(format: str, status: str = "ready") -> Dict[str, str]:
    """Build common image response headers."""
    return {
        "Cache-Control": "public, max-age=86400, s-maxage=86400, immutable",
        "CDN-Cache-Control": "public, s-maxage=86400, immutable",
        "Content-Type": _format_to_media_type(format),
        "Access-Control-Allow-Origin": "*",
        "Cross-Origin-Resource-Policy": "cross-origin",
        "X-Screenshot-Status": status,
    }


def _no_cache_headers() -> Dict[str, str]:
    """Headers for dynamic non-cacheable responses."""
    return {
        "Cache-Control": "no-store, no-cache, max-age=0, must-revalidate",
        "CDN-Cache-Control": "no-store",
        "Pragma": "no-cache",
    }


def _status_headers(
    format: str, status: str, job_id: Optional[str] = None
) -> Dict[str, str]:
    """Build headers for non-ready HEAD screenshot responses."""
    headers = {
        "Content-Type": _format_to_media_type(format),
        "Access-Control-Allow-Origin": "*",
        "Cross-Origin-Resource-Policy": "cross-origin",
        "X-Screenshot-Status": status,
    }
    headers.update(_no_cache_headers())
    if job_id is not None:
        headers["X-Job-Id"] = job_id
    return headers


def _json_no_cache_response(
    content: Dict[str, object], status_code: int = 200
) -> JSONResponse:
    """Return JSON response that should never be cached by edge/CDN."""
    return JSONResponse(content, status_code=status_code, headers=_no_cache_headers())


def _build_requested_filename(
    url: str,
    width: int,
    height: int,
    scaled_width: int,
    scaled_height: int,
    selectors: Optional[str],
    format: str,
    version: Optional[int],
    theme: Optional[str],
) -> str:
    """Build the storage filename for a screenshot request."""
    selector_list = selectors.split(",") if selectors else []
    return build_image_name(
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


def _record_url_request(url: str, filename: str, method: str) -> None:
    """Persist source URL request stats for later reporting."""
    get_queue().record_url_request(url=url, filename=filename, method=method)


async def _serve_image(filename: str, format: str, method: str):
    """Serve image from object storage."""
    if method == "HEAD":
        return Response(headers=_image_headers(format), status_code=200)

    imgdata = await config.s3_client.get_file(filename)
    return StreamingResponse(
        content=imgdata,
        media_type=_format_to_media_type(format),
        headers=_image_headers(format),
    )


async def _get_async_shot_response(
    request_method: str,
    url: str,
    width: int,
    height: int,
    scaled_width: int,
    scaled_height: int,
    selectors: Optional[str],
    format: str,
    version: Optional[int],
    timeout_ms: Optional[int],
    theme: Optional[str],
):
    """Return async queue-oriented response for screenshot requests."""
    imgname = _build_requested_filename(
        url,
        width,
        height,
        scaled_width,
        scaled_height,
        selectors,
        format,
        version,
        theme,
    )
    _record_url_request(url=url, filename=imgname, method=request_method)

    if config.s3_client.file_exists(imgname):
        if request_method == "HEAD":
            return Response(headers=_image_headers(format), status_code=200)

        return _json_no_cache_response(
            {
                "status": "exists",
                "filename": imgname,
                "result_url": f"/shot/{imgname}",
            },
            status_code=200,
        )

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
        theme,
    ):
        job_id = queue.get_job_id_by_filename(imgname)
        if request_method == "HEAD":
            headers = _status_headers(format, "processing", job_id or "")
            return Response(headers=headers, status_code=202)

        return _json_no_cache_response(
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
        theme=theme,
        priority=0,
    )

    if request_method == "HEAD":
        headers = _status_headers(format, "queued", job_id)
        return Response(headers=headers, status_code=202)

    return _json_no_cache_response(
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


async def _get_blocking_shot_response(
    request_method: str,
    url: str,
    width: int,
    height: int,
    scaled_width: int,
    scaled_height: int,
    selectors: Optional[str],
    format: str,
    version: Optional[int],
    timeout_ms: Optional[int],
    theme: Optional[str],
    wait_ms: int,
):
    """Queue, wait for completion, and return image response."""
    imgname = _build_requested_filename(
        url,
        width,
        height,
        scaled_width,
        scaled_height,
        selectors,
        format,
        version,
        theme,
    )
    _record_url_request(url=url, filename=imgname, method=request_method)

    if config.s3_client.file_exists(imgname):
        return await _serve_image(imgname, format, request_method)

    queue = get_queue()
    job_id = queue.get_job_id_by_filename(imgname)
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
            theme=theme,
            priority=0,
        )

    deadline = time.monotonic() + (wait_ms / 1000)
    while time.monotonic() < deadline:
        if config.s3_client.file_exists(imgname):
            return await _serve_image(imgname, format, request_method)

        job_data = queue.get_job(job_id)
        if job_data and job_data.get("status") == "failed":
            raise HTTPException(
                status_code=500,
                detail=job_data.get("error") or "Screenshot job failed",
            )

        await asyncio.sleep(0.5)

    raise HTTPException(
        status_code=504,
        detail=f"Timed out waiting for screenshot after {wait_ms}ms",
    )


@app.get("/")
def get(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "env": os.environ,
        },
    )


@app.get("/dashboard")
@app.get("/dashboard/")
@app.get("/dashboard/urls")
def get_url_dashboard(
    request: Request,
    limit: int = Query(default=100, ge=1, le=1000),
    page: int = Query(default=1, ge=1),
    filenames_per_url: int = Query(default=3, ge=1, le=20),
):
    """Render a small dashboard for tracked URL request stats."""
    queue = get_queue()
    offset = (page - 1) * limit
    stats = queue.get_url_stats(
        limit=limit,
        offset=offset,
        filenames_per_url=filenames_per_url,
    )
    queue_stats = queue.get_queue_stats()
    now = time.time()
    active_jobs = []
    for job in queue.get_active_jobs():
        started_processing_at = job.get("started_processing_at")
        created_at = job.get("created_at")
        worker_seconds = 0.0
        queued_seconds = 0.0
        if isinstance(started_processing_at, (int, float)):
            worker_seconds = round(max(0.0, now - started_processing_at), 1)
        if not worker_seconds and isinstance(created_at, (int, float)):
            queued_seconds = round(max(0.0, now - created_at), 1)
        active_jobs.append(
            {
                **job,
                "worker_seconds": worker_seconds,
                "queued_seconds": queued_seconds,
            }
        )
    storage_backend = (config.storage_backend or "s3").lower()
    storage_details = [
        {"label": "Backend", "value": storage_backend},
    ]
    if storage_backend == "local":
        storage_details.append(
            {"label": "Directory", "value": config.local_storage_dir or ".cache/shots"}
        )
    else:
        storage_details.extend(
            [
                {"label": "Bucket", "value": config.aws_bucket_name or "(not set)"},
                {
                    "label": "Endpoint",
                    "value": config.aws_endpoint_url or "AWS S3 default",
                },
            ]
        )
    storage = {
        "details": storage_details,
        "runtime": [
            {
                "label": "Workers",
                "value": str(config.queue_processor_concurrency),
            },
            {
                "label": "Render limit",
                "value": str(
                    config.render_concurrency or config.queue_processor_concurrency
                ),
            },
            {
                "label": "Post-process limit",
                "value": str(
                    config.postprocess_concurrency or config.queue_processor_concurrency
                ),
            },
        ],
        "queue_backend": (config.queue_backend or "auto").lower(),
    }
    total_pages = max(1, (stats["total_urls"] + limit - 1) // limit)

    def _page_url(target_page: int) -> str:
        params = dict(request.query_params)
        params["page"] = str(target_page)
        params["limit"] = str(limit)
        params["filenames_per_url"] = str(filenames_per_url)
        return str(request.url.include_query_params(**params))

    pagination = {
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
        "prev_url": _page_url(page - 1) if page > 1 else None,
        "next_url": _page_url(page + 1) if page < total_pages else None,
    }
    response = templates.TemplateResponse(
        "url_dashboard.html",
        {
            "request": request,
            "stats": stats,
            "queue_stats": queue_stats,
            "active_jobs": active_jobs,
            "storage": storage,
            "refreshed_at": int(now),
            "dashboard_limit": limit,
            "dashboard_page": page,
            "filenames_per_url": filenames_per_url,
            "pagination": pagination,
        },
    )
    for key, value in _no_cache_headers().items():
        response.headers[key] = value
    return response


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
    theme: Optional[str] = Query(default=None),
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

    parsed_theme = _parse_theme(theme)

    # Validate priority
    if not (0 <= priority <= 10):
        raise HTTPException(
            status_code=400,
            detail="Priority must be between 0 (low) and 10 (high)",
        )

    # Check if already exists in S3
    imgname = _build_requested_filename(
        url,
        width,
        height,
        scaled_width or width,
        scaled_height or height,
        selectors,
        format,
        version,
        parsed_theme,
    )
    _record_url_request(url=url, filename=imgname, method=request.method)

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
        parsed_theme,
    ):
        job_id = queue.get_job_id_by_filename(imgname)
        return _json_no_cache_response(
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
        return _json_no_cache_response(
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
        theme=parsed_theme,
        priority=priority,
    )

    console.log(f"Queued screenshot job {job_id} for {url}")

    return _json_no_cache_response(
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

    return _json_no_cache_response(job_data)


@app.get("/queue/stats")
async def get_queue_stats():
    """Get queue statistics"""
    queue = get_queue()
    stats = queue.get_queue_stats()
    return _json_no_cache_response(stats)


@app.post("/queue/cleanup")
async def cleanup_queue_jobs(
    completed_age_hours: int = Query(default=24, ge=0),
    stale_age_minutes: int = Query(default=30, ge=0),
    dry_run: bool = Query(default=False),
):
    """Clean up old terminal jobs and stale active jobs."""
    queue = get_queue()
    result = queue.cleanup_old_jobs(
        max_age_hours=completed_age_hours,
        stale_age_minutes=stale_age_minutes,
        dry_run=dry_run,
    )
    return _json_no_cache_response(result)


@app.get("/url/stats")
@app.get("/urls/stats")
async def get_url_stats():
    """List tracked source URLs and request counts."""
    queue = get_queue()
    return _json_no_cache_response(queue.get_url_stats())


@app.api_route("/shot/blocking", methods=["GET", "HEAD"])
@app.api_route("/shot/blocking/", methods=["GET", "HEAD"])
async def get_shot_blocking(
    request: Request,
    url: str = Query(...),
    height: Optional[int] = 450,
    width: Optional[int] = 800,
    scaled_height: Optional[int | str] = None,
    scaled_width: Optional[int | str] = None,
    selectors: Optional[str] = None,
    format: Optional[str] = None,
    v: Optional[str] = Query(default=None),
    timeout: Optional[str] = Query(default=None),
    theme: Optional[str] = Query(default=None),
    wait: int = Query(default=30000, description="Max wait time in milliseconds"),
):
    """Block until screenshot is ready and return image bytes."""
    format = _normalize_format(format)

    if not url.startswith("http"):
        raise HTTPException(status_code=404, detail="url is not a url")

    if wait <= 0:
        raise HTTPException(status_code=400, detail="wait must be a positive integer")
    if wait > 120000:
        raise HTTPException(status_code=400, detail="wait cannot exceed 120000 ms")

    width = width or 800
    height = height or 450
    scaled_height = int(scaled_height) if scaled_height else height
    scaled_width = int(scaled_width) if scaled_width else width
    version = _parse_version(v)
    timeout_ms = _parse_timeout(timeout)
    parsed_theme = _parse_theme(theme)
    return await _get_blocking_shot_response(
        request_method=request.method,
        url=url,
        width=width,
        height=height,
        scaled_width=scaled_width,
        scaled_height=scaled_height,
        selectors=selectors,
        format=format,
        version=version,
        timeout_ms=timeout_ms,
        theme=parsed_theme,
        wait_ms=wait,
    )


@app.api_route("/shot/async", methods=["GET", "HEAD"])
@app.api_route("/shot/async/", methods=["GET", "HEAD"])
async def get_shot_async(
    request: Request,
    url: str = Query(...),
    height: Optional[int] = 450,
    width: Optional[int] = 800,
    scaled_height: Optional[int | str] = None,
    scaled_width: Optional[int | str] = None,
    selectors: Optional[str] = None,
    format: Optional[str] = None,
    v: Optional[str] = Query(default=None),
    timeout: Optional[str] = Query(default=None),
    theme: Optional[str] = Query(default=None),
):
    """Return queue status JSON instead of blocking for image bytes."""
    format = _normalize_format(format)

    if not url.startswith("http"):
        raise HTTPException(status_code=404, detail="url is not a url")

    width = width or 800
    height = height or 450
    scaled_height = int(scaled_height) if scaled_height else height
    scaled_width = int(scaled_width) if scaled_width else width

    version = _parse_version(v)
    timeout_ms = _parse_timeout(timeout)
    parsed_theme = _parse_theme(theme)

    return await _get_async_shot_response(
        request_method=request.method,
        url=url,
        width=width,
        height=height,
        scaled_width=scaled_width,
        scaled_height=scaled_height,
        selectors=selectors,
        format=format,
        version=version,
        timeout_ms=timeout_ms,
        theme=parsed_theme,
    )


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
    theme: Optional[str] = Query(default=None),
    wait: int = Query(default=30000, description="Max wait time in milliseconds"),
    mode: Optional[str] = Query(default=None),
):
    format = _normalize_format(format, filename)

    if url is None:
        if not filename:
            raise HTTPException(status_code=400, detail="url is required")

        return await _serve_image(filename, format, request.method)

    scaled_height = int(scaled_height) if scaled_height else height
    scaled_width = int(scaled_width) if scaled_width else width

    # Ensure width and height are not None for take_screenshot
    width = width or 800
    height = height or 450

    # Ensure scaled dimensions are integers (not None)
    scaled_height = int(scaled_height) if scaled_height else height
    scaled_width = int(scaled_width) if scaled_width else width

    if not url.startswith("http"):
        raise HTTPException(status_code=404, detail="url is not a url")

    version = _parse_version(v)
    timeout_ms = _parse_timeout(timeout)
    parsed_theme = _parse_theme(theme)

    # Handle HTMX requests (only for GET)
    hx_request_header = request.headers.get("hx-request")
    if hx_request_header and request.method == "GET":
        imgname = _build_requested_filename(
            url,
            width,
            height,
            scaled_width,
            scaled_height,
            selectors,
            format,
            version,
            parsed_theme,
        )
        _record_url_request(url=url, filename=imgname, method=request.method)
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
                    theme=parsed_theme,
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
                "theme": parsed_theme,
                "job_id": job_id,
                "status": status,
            },
        )

    if mode == "async" or request.method == "HEAD":
        return await _get_async_shot_response(
            request_method=request.method,
            url=url,
            width=width,
            height=height,
            scaled_width=scaled_width,
            scaled_height=scaled_height,
            selectors=selectors,
            format=format,
            version=version,
            timeout_ms=timeout_ms,
            theme=parsed_theme,
        )

    if wait <= 0:
        raise HTTPException(status_code=400, detail="wait must be a positive integer")
    if wait > 120000:
        raise HTTPException(status_code=400, detail="wait cannot exceed 120000 ms")

    return await _get_blocking_shot_response(
        request_method=request.method,
        url=url,
        width=width,
        height=height,
        scaled_width=scaled_width,
        scaled_height=scaled_height,
        selectors=selectors,
        format=format,
        version=version,
        timeout_ms=timeout_ms,
        theme=parsed_theme,
        wait_ms=wait,
    )


@app.delete("/shot")
@app.delete("/shot/")
@app.delete("/shot/{filename}")
@app.delete("/shot/{filename}/")
async def delete_shot(
    filename: Optional[str] = None,
    url: Optional[str] = Query(default=None),
    height: Optional[int] = 450,
    width: Optional[int] = 800,
    scaled_height: Optional[int | str] = None,
    scaled_width: Optional[int | str] = None,
    selectors: Optional[str] = None,
    format: Optional[str] = None,
    v: Optional[str] = Query(default=None),
    theme: Optional[str] = Query(default=None),
):
    """Delete an existing screenshot object from storage."""
    resolved_filename = filename

    if not resolved_filename:
        if not url:
            raise HTTPException(
                status_code=400,
                detail="Provide either filename path or url query parameters",
            )
        if not url.startswith("http"):
            raise HTTPException(status_code=404, detail="url is not a url")

        normalized_format = _normalize_format(format)
        version = _parse_version(v)
        parsed_theme = _parse_theme(theme)

        width = width or 800
        height = height or 450
        scaled_height = int(scaled_height) if scaled_height else height
        scaled_width = int(scaled_width) if scaled_width else width
        selector_list = selectors.split(",") if selectors else []

        resolved_filename = build_image_name(
            url,
            selector_list,
            width,
            height,
            scaled_width,
            scaled_height,
            normalized_format,
            version,
            parsed_theme,
        )
    else:
        _normalize_format(format=None, filename=resolved_filename)

    if not config.s3_client.file_exists(resolved_filename):
        raise HTTPException(status_code=404, detail="Shot not found")

    await config.s3_client.delete_file(resolved_filename)
    return _json_no_cache_response(
        {
            "status": "deleted",
            "filename": resolved_filename,
        }
    )
