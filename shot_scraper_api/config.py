from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings
from rich.console import Console
from typing import Optional

from shot_scraper_api.s3 import S3Client


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
    api_server_host: str = "0.0.0.0"
    api_server_port: int = 8000

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


@lru_cache()
def get_config() -> Config:
    """Get cached config instance."""

    config = Config()
    config.console.print(config)
    return config


# Create a global config instance
config = get_config()
