import asyncio
from pathlib import Path

from shot_scraper_api.config import Config
from shot_scraper_api.s3 import LocalStorageClient


def test_config_uses_local_storage_backend(tmp_path):
    config = Config(storage_backend="local", local_storage_dir=str(tmp_path / "shots"))

    client = config.storage_client

    assert isinstance(client, LocalStorageClient)
    assert client.storage_dir == tmp_path / "shots"


def test_local_storage_client_round_trip(tmp_path):
    source = tmp_path / "source.txt"
    source.write_bytes(b"hello world")
    client = LocalStorageClient(storage_dir=tmp_path / "shots")

    async def exercise() -> None:
        uploaded = await client.upload_file(str(source), "example.txt")
        assert Path(uploaded).name == "example.txt"
        assert client.file_exists("example.txt") is True

        chunks = []
        async for chunk in await client.get_file("example.txt"):
            chunks.append(chunk)
        assert b"".join(chunks) == b"hello world"

        assert await client.get_file_url("example.txt") == "/shot/example.txt"

        await client.delete_file("example.txt")
        assert client.file_exists("example.txt") is False

    asyncio.run(exercise())
