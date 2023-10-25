from fastapi import FastAPI, Request, HTTPException
from minio import Minio
from minio.error import S3Error
import hashlib
import os
from pathlib import Path
import subprocess
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.responses import FileResponse
from shot_scraper_api.console import console
from fastapi.templating import Jinja2Templates


app = FastAPI()

templates = Jinja2Templates(directory="templates")

ACCESS_KEY = os.environ.get("ACCESS_KEY")
SECRET_KEY = os.environ.get("SECRET_KEY")


@app.get("/")
def get(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "env": os.environ,
        },
    )


@app.get("/shot/", responses={200: {"content": {"image/png": {}}}})
async def get_shot(request: Request, path: str):
    if not path.startswith("http"):
        raise HTTPException(status_code=404, detail="path is not a url")

    imgname = (hashlib.md5(path.encode()).hexdigest() + ".png").lower()
    output = "/tmp/" + imgname
    output_webp = output.replace(".png", ".webp")
    client = Minio(
        "sandcrawler.wayl.one",
        access_key=ACCESS_KEY,
        secret_key=SECRET_KEY,
    )
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
        path,
        "-h",
        "450",
        "-w",
        "800",
        "-o",
        output,
        "--wait",
        "2000",
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
        "722",
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
