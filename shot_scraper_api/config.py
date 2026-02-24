from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings
from rich.console import Console
from typing import Optional

from shot_scraper_api.s3 import S3Client

from pydantic import BaseModel


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
    redis_url: Optional[str] = Field(None)
    queue_backend: Optional[str] = Field("auto")
    queue_namespace: Optional[str] = Field("shot-scraper")
    queue_processor_enabled: bool = Field(True)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "allow"

    @property
    def s3_client(self):
        return S3Client(self)

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
            redis_url=redact(config.redis_url),
            queue_backend=config.queue_backend,
            queue_namespace=config.queue_namespace,
            queue_processor_enabled=config.queue_processor_enabled,
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
