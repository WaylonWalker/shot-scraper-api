import hashlib
import os
from pathlib import Path
import subprocess
from typing import Optional
from urllib.parse import quote_plus

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from minio import Minio
from minio.error import S3Error

from shot_scraper_api.console import console

app = FastAPI()
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
ENV = os.environ["ENV"]

ACCESS_KEY = os.environ.get("ACCESS_KEY").strip("\n")
SECRET_KEY = os.environ.get("SECRET_KEY").strip("\n")

if ENV == "dev":
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
    responses={200: {"content": {"image/webp": {}, "image/png": {}, "image/jpeg": {}}}},
)
@app.get(
    "/shot",
    responses={200: {"content": {"image/webp": {}, "image/png": {}, "image/jpeg": {}}}},
)
@app.get(
    "/shot/{filename}",
    responses={200: {"content": {"image/webp": {}, "image/png": {}, "image/jpeg": {}}}},
)
@app.get(
    "/shot/{filename}/",
    responses={200: {"content": {"image/webp": {}, "image/png": {}, "image/jpeg": {}}}},
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
    cmd_selectors = []

    for selector in selectors.split(",") if selectors else []:
        cmd_selectors.append("-s")
        cmd_selectors.append(selector)

    if not url.startswith("http"):
        raise HTTPException(status_code=404, detail="url is not a url")

    hx_request_header = request.headers.get("hx-request")
    imgname = (
        hashlib.md5(f"{url}{''.join(cmd_selectors)}".encode()).hexdigest()
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
    client = Minio(
        "minio.wayl.one",
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
    )
    print(f"getting {imgname} from minio")
    try:
        imgdata = client.get_object("shots", imgname)
        print("streaming from minio")
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

    except S3Error:
        print(f"failed to get {imgname} from minio")

    cmd = [
        "shot-scraper",
        url,
        "-h",
        str(height),
        "-w",
        str(width),
        "-o",
        output,
        "--wait",
        "2000",
        *cmd_selectors,
    ]
    console.log(f"running {cmd}")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    proc.wait()
    console.log(proc.stdout.read().decode())
    console.log(proc.stderr.read().decode())
    cmd = [
        "convert",
        output,
        "-resize",
        f"{scaled_width}x{scaled_height}",
        output,
    ]
    if Path(output).exists():
        console.log(f"running {cmd}")
        resize_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        resize_proc.wait()
        console.log(proc.stdout.read().decode())
        console.log(proc.stderr.read().decode())

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
        convert_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        convert_proc.wait()
        console.log(proc.stdout.read().decode())
        console.log(proc.stderr.read().decode())

    if Path(output_final).exists():
        print("putting", output_final, imgname)
        client.fput_object(
            "shots",
            imgname,
            output_final,
        )

    try:
        imgdata = client.get_object("shots", imgname)
        print("streaming from minio")

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

    except S3Error:
        raise HTTPException(status_code=404, detail="image not found")
