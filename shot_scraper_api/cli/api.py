import typer

from shot_scraper_api.config import config
from shot_scraper_api.console import console
import uvicorn

api_app = typer.Typer()


@api_app.callback()
def api(
    verbose: bool = typer.Option(
        False,
        help="show the log messages",
    ),
):
    "model cli"


@api_app.command()
def run(
    env: str = typer.Option(
        "dev",
        help="environment to run",
    ),
):
    console.quiet = False
    console.log(f"running {env}")
    uvicorn.run(**config.get("api_server", {}).get(env, "dev"))
