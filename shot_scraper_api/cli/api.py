import os
import typer

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
    os.environ["ENV"] = env
    console.quiet = False
    console.log(f"running {env}")
    uvicorn.run(
        "shot_scraper_api.api.app:app",
        # host=config.api_server_host,
        # port=config.api_server_port,
        host="0.0.0.0",
        port=5000,
    )
