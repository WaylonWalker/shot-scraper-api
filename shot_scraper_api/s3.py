import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError
import io
import logging
import os


class S3Client:
    def __init__(self, config):
        session = (
            boto3.Session(profile_name=config.aws_profile)
            if config.aws_profile
            else boto3.Session()
        )

        # Configure client with s3v4 signature and path-style addressing
        boto_config = BotoConfig(
            retries=dict(max_attempts=3),
            signature_version="s3v4",
            s3={"addressing_style": "path"},
        )

        client_args = {
            "service_name": "s3",
            "config": boto_config,
        }

        if config.aws_endpoint_url:
            client_args.update(
                {
                    "endpoint_url": config.aws_endpoint_url,
                    "aws_access_key_id": config.aws_access_key_id,
                    "aws_secret_access_key": config.aws_secret_access_key,
                    "region_name": config.aws_region,
                }
            )

        self.s3 = session.client(**client_args)
        self.config = config
        # self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        """Ensure the configured bucket exists, create if it doesn't"""
        try:
            self.s3.head_bucket(Bucket=self.config.aws_bucket_name)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code")
            if error_code == "404" or error_code == "NoSuchBucket":
                # Create bucket if it doesn't exist
                try:
                    if self.config.aws_endpoint_url:
                        # For MinIO/local S3, don't specify region
                        self.s3.create_bucket(Bucket=self.config.aws_bucket_name)
                    else:
                        # For AWS S3, specify region
                        self.s3.create_bucket(
                            Bucket=self.config.aws_bucket_name,
                            CreateBucketConfiguration={
                                "LocationConstraint": self.config.aws_region
                            },
                        )
                except ClientError as create_error:
                    raise Exception(f"Failed to create bucket: {str(create_error)}")
            else:
                raise Exception(f"Failed to access bucket: {str(e)}")

    async def upload_file(self, filepath: str, filename: str | None = None) -> str:
        """Upload a file to S3 bucket and return its URL

        Args:
            filepath: Path to the file to upload
            filename: Optional custom filename to use in S3. If not provided, uses basename of filepath
        """
        try:
            if not os.path.exists(filepath):
                raise FileNotFoundError(f"File not found: {filepath}")

            # Use provided filename or extract from path
            if filename is None:
                filename = os.path.basename(filepath)

            # Check file size
            size = os.path.getsize(filepath)
            if size > self.config.max_file_size_mb * 1024 * 1024:
                raise ValueError(
                    f"File size exceeds maximum allowed size of {self.config.max_file_size_mb} mb"
                )

            with open(filepath, "rb") as file:
                self.s3.upload_fileobj(file, self.config.aws_bucket_name, filename)
        except ClientError as e:
            raise Exception(f"Failed to upload file to S3: {str(e)}")

    async def upload_bytes(self, filename: str, content: bytes) -> str:
        """Upload bytes content to S3 bucket and return its URL"""
        try:
            # Check file size
            size = len(content)

            if size > config.MAX_FILE_SIZE:
                raise ValueError(
                    f"File size exceeds maximum allowed size of {config.MAX_FILE_SIZE} bytes"
                )

            # Create file-like object from bytes
            file_obj = io.BytesIO(content)

            self.s3.upload_fileobj(file_obj, self.config.aws_bucket_name, filename)

            # Generate URL based on endpoint
            if config.AWS_ENDPOINT_URL:
                url = f"{config.AWS_ENDPOINT_URL}/{self.config.aws_bucket_name}/{filename}"
            else:
                url = (
                    f"https://{self.config.aws_bucket_name}.s3.amazonaws.com/{filename}"
                )
            return url
        except ClientError as e:
            raise Exception(f"Failed to upload file to S3: {str(e)}")

    async def get_file(self, filename: str):
        """Get a file from S3 as a streaming response"""
        try:
            response = self.s3.get_object(
                Bucket=self.config.aws_bucket_name, Key=filename
            )

            async def stream_response():
                chunk_size = 8192  # 8KB chunks
                body = response["Body"]
                while True:
                    chunk = body.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk

            return stream_response()
        except ClientError as e:
            raise Exception(f"Failed to get file from S3: {str(e)}")

    async def get_file_url(self, filename: str, expires_in: int = 31536000) -> str:
        """Generate a presigned URL for file download"""
        try:
            url = self.generate_presigned_url(
                object_name=filename,
                content_type="image/webp",
                expiration=expires_in,
                http_method="get",
                download=False,
            )
            return url
        except ClientError as e:
            raise Exception(f"Failed to generate presigned URL: {str(e)}")

    async def delete_file(self, filename: str) -> None:
        """Delete a file from S3 bucket"""
        try:
            self.s3.delete_object(Bucket=self.config.aws_bucket_name, Key=filename)
        except ClientError as e:
            raise Exception(f"Failed to delete file from S3: {str(e)}")

    async def list_files(self, prefix: str = None):
        """List all files in the bucket, optionally filtered by prefix"""
        try:
            params = {"Bucket": self.config.aws_bucket_name}
            if prefix:
                params["Prefix"] = prefix

            response = self.s3.list_objects_v2(**params)

            files = []
            if "Contents" in response:
                for obj in response["Contents"]:
                    # Infer content type from extension
                    ext = obj["Key"].split(".")[-1].lower() if "." in obj["Key"] else ""
                    content_type = {
                        "webp": "image/webp",
                        "jpg": "image/jpeg",
                        "jpeg": "image/jpeg",
                        "png": "image/png",
                        "gif": "image/gif",
                    }.get(ext, "application/octet-stream")

                    files.append(
                        {
                            "key": obj["Key"],
                            "size": obj["Size"],
                            "last_modified": obj["LastModified"].isoformat(),
                            "content_type": content_type,
                        }
                    )

            return files
        except ClientError as e:
            raise Exception(f"Failed to list files: {str(e)}")

    def file_exists(self, filename: str) -> bool:
        """Check if a file exists in the S3 bucket.

        Args:
            filename: The name of the file (key) in the S3 bucket.

        Returns:
            bool: True if the file exists, False otherwise.
        """
        try:
            self.s3.get_object(Bucket=self.config.aws_bucket_name, Key=filename)
            return True
        except self.s3.exceptions.ClientError as e:
            error_code = e.response["Error"]["Code"]
            if error_code in ["404", "NoSuchKey"]:
                return False
            raise Exception(f"Error checking file existence: {str(e)}")

    def generate_presigned_url(
        self,
        object_name: str,
        content_type: str = None,
        expiration: int = 3600,
        http_method: str = "put",
        download: bool = False,
    ) -> str:
        """Generate a presigned URL for uploading or downloading a file."""
        try:
            params = {
                "Bucket": self.config.aws_bucket_name,
                "Key": object_name,
            }

            # Add content type or response headers based on HTTP method
            if http_method.lower() == "put" and content_type:
                params["ContentType"] = content_type
            elif http_method.lower() == "get":
                params["ResponseContentType"] = (
                    content_type or "application/octet-stream"
                )
                if download:
                    params["ResponseContentDisposition"] = "attachment"

            # MinIO requires the region in the signature to be "us-east-1"
            if self.config.aws_endpoint_url:
                region = self.config.aws_region or "us-east-1"
                self.s3.meta.events.register(
                    "choose-signer.s3.*", lambda **kwargs: "s3v4"
                )
                # self.s3.meta.client._client_config.region_name = region

            # Generate the URL
            url = self.s3.generate_presigned_url(
                ClientMethod=f"{http_method}_object",
                Params=params,
                # ExpiresIn=expiration,
                ExpiresIn=3600,
                HttpMethod=http_method.upper(),
            )

            # Cache the URL (optional)
            # with Cache(Path(self.config.cache_dir) / "s3") as cache:
            #     cache_key = f"{self.config.aws_bucket_name}:{object_name}:{http_method}:{download}"
            #     cache.set(cache_key, url, expire=max(60, expiration - 3600))

            return url
        except ClientError as e:
            logging.error(f"Error generating presigned URL: {e}")
            raise
