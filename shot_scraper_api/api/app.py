from fastapi import FastAPI, Request, HTTPException
from typing import Optional
from minio import Minio
from minio.error import S3Error
import hashlib
import os
from pathlib import Path
import subprocess
from fastapi.responses import StreamingResponse, HTMLResponse
from shot_scraper_api.console import console
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from shot_scraper_api.config import config


app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

templates = Jinja2Templates(directory="templates")
ENV = os.environ["ENV"]

ACCESS_KEY = os.environ.get("ACCESS_KEY")
SECRET_KEY = os.environ.get("SECRET_KEY")

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


@app.get("/shot", responses={200: {"content": {"image/webp": {}}}})
@app.get("/shot/", responses={200: {"content": {"image/webp": {}}}})
async def get_shot(
    request: Request,
    url: str,
    height: Optional[int] = 450,
    width: Optional[int] = 800,
    scaled_height: Optional[int | str] = None,
    scaled_width: Optional[int | str] = None,
    selectors: Optional[str] = None,
):
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
        + f"-{width}x{height}-{scaled_width}x{scaled_height}.png"
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

    output = "/tmp/" + imgname
    output_webp = output.replace(".png", ".webp")
    client = Minio(
        "sandcrawler.wayl.one",
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
    )
    print(f"getting {imgname} from minio")
    try:
        imgdata = client.get_object("images.thoughts", imgname.replace(".png", ".webp"))
        print("streaming from minio")
        return StreamingResponse(
            content=imgdata,
            media_type="image/webp",
            headers={"Cache-Control": "max-age=604800"},
        )

    except S3Error:
        print(f'failed to get {imgname.replace(".png", ".webp")} from minio')

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
    res = proc.wait()
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
        res = resize_proc.wait()
        console.log(proc.stdout.read().decode())
        console.log(proc.stderr.read().decode())
    cmd = [
        "cwebp",
        "-q",
        "80",
        output,
        "-o",
        output_webp,
    ]
    if Path(output).exists():
        console.log(f"running {cmd}")
        webp_proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        res = webp_proc.wait()
        console.log(proc.stdout.read().decode())
        console.log(proc.stderr.read().decode())

    if Path(output_webp).exists():
        print("putting", output, imgname.replace(".png", ".webp"))
        client.fput_object(
            "images.thoughts",
            imgname.replace(".png", ".webp"),
            output_webp,
        )

    try:
        imgdata = client.get_object("images.thoughts", imgname.replace(".png", ".webp"))
        print("streaming from minio")

        # cache for 7 days
        return StreamingResponse(
            content=imgdata,
            media_type="image/webp",
            headers={"Cache-Control": "max-age=604800"},
        )

    except S3Error:
        HTTPException(status_code=404, detail="image not found")
