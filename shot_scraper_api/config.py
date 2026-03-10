from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings
from rich.console import Console

from shot_scraper_api.s3 import LocalStorageClient, S3Client


def redact(value: str | None, keep: int = 4) -> str | None:
    if not value:
        return value
    return value[:keep] + "*" * (len(value) - keep)


class Config(BaseSettings):
    # Base Paths
    env: str = "dev"
    aws_profile: Optional[str] = Field(None)
    aws_access_key_id: Optional[str] = Field(None)
    aws_secret_access_key: Optional[str] = Field(None)
    aws_region: Optional[str] = Field(None)
    aws_endpoint_url: Optional[str] = Field(None)
    aws_bucket_name: Optional[str] = Field(None)
    docker_repo: Optional[str] = Field(None)
    max_file_size_mb: Optional[int] = Field(100)
    cache_dir: Optional[str] = Field("/cache/")
    storage_backend: Optional[str] = Field("s3")
    local_storage_dir: Optional[str] = Field(".cache/shots")
    redis_url: Optional[str] = Field(None)
    queue_backend: Optional[str] = Field("auto")
    queue_namespace: Optional[str] = Field("shot-scraper")
    queue_processor_enabled: bool = Field(True)
    queue_processor_concurrency: int = Field(2)
    render_concurrency: Optional[int] = Field(None)
    postprocess_concurrency: Optional[int] = Field(None)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "allow"

    @property
    def storage_client(self):
        backend = (self.storage_backend or "s3").lower()
        if backend == "local":
            storage_dir = Path(self.local_storage_dir or ".cache/shots")
            return LocalStorageClient(storage_dir=storage_dir)
        return S3Client(self)

    @property
    def s3_client(self):
        return self.storage_client

    @property
    def s3fs(self):
        import s3fs

        return s3fs.S3FileSystem(
            key=self.aws_access_key_id,
            secret=self.aws_secret_access_key,
            endpoint_url=self.aws_endpoint_url,
            client_kwargs={
                "endpoint_url": self.aws_endpoint_url,
                "region_name": self.aws_region,
            },
        )

    @property
    def console(self):
        return Console()


class SafeConfig(Config):
    @classmethod
    def from_config(cls, config):
        return cls(
            env=config.env,
            aws_access_key_id=redact(config.aws_access_key_id),
            aws_secret_access_key=redact(config.aws_secret_access_key),
            aws_endpoint_url=config.aws_endpoint_url,
            aws_bucket_name=config.aws_bucket_name,
            cache_dir=config.cache_dir,
            storage_backend=config.storage_backend,
            local_storage_dir=config.local_storage_dir,
            redis_url=redact(config.redis_url),
            queue_backend=config.queue_backend,
            queue_namespace=config.queue_namespace,
            queue_processor_enabled=config.queue_processor_enabled,
            queue_processor_concurrency=config.queue_processor_concurrency,
            render_concurrency=config.render_concurrency,
            postprocess_concurrency=config.postprocess_concurrency,
        )


@lru_cache()
def get_config() -> Config:
    """Get cached config instance."""

    config = Config()
    safe_config = SafeConfig.from_config(config)
    config.console.print(safe_config)
    return config


# Create a global config instance
config = get_config()
