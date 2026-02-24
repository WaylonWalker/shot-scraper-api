# AGENTS.md

This file contains guidelines and commands for agentic coding agents working in the shot-scraper-api repository.

## Project Overview

Shot Scraper API is a FastAPI-based web service for taking screenshots of web pages. It uses Pyppeteer for browser automation, S3/MinIO for file storage, and includes both REST API and TUI interfaces.

**Key Technologies:**
- FastAPI (web framework)
- Pyppeteer (browser automation)
- boto3/botocore (AWS S3 integration)
- Typer (CLI framework)
- Textual (TUI framework)
- Pydantic (settings/validation)
- Rich (terminal output)

## Development Commands

### Environment Setup
```bash
# Create virtual environment (if using uv)
uv venv
source .venv/bin/activate  # Linux/Mac
# or .venv\Scripts\activate  # Windows

# Install dependencies
uv pip install -e .
```

### Code Quality & Testing
```bash
# Run linting (ruff)
hatch run lint

# Run formatting (black)
hatch run format

# Check formatting without changes
hatch run format-check

# Run tests with coverage
hatch run test

# Run single test file
hatch run pytest tests/test_specific_file.py

# Run single test function
hatch run pytest tests/test_file.py::test_function

# Generate coverage report
hatch run cov

# Run all quality checks together
hatch run lint-test
```

### Development Server
```bash
# Start development server with hot reload
uvicorn shot_scraper_api.api.app:app --reload --host 0.0.0.0 --port 5000

# Or use hatch environment
hatch run dev
```

### Docker & Deployment
```bash
# Build Docker image
just build

# Run with Docker
docker run -p 5050:5000 --env-file .env shot-scraper-api

# Kubernetes deployment
just fresh  # Full deployment pipeline
```

## Code Style Guidelines

### Import Organization
- Use `isort` (handled by ruff) for import sorting
- Standard library imports first, then third-party, then local
- Use `from typing import Optional, Union` for type hints
- Avoid wildcard imports (`from module import *`)

**Example:**
```python
import asyncio
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from shot_scraper_api.config import config
from shot_scraper_api.s3 import S3Client
```

### Type Hints
- Use type hints for all function parameters and return values
- Use `Optional[T]` for nullable values
- Use `Union[T, U]` or `T | U` (Python 3.10+) for multiple types
- Use `List[T]`, `Dict[K, V]` for collections
- Add `-> None` for functions that don't return values

**Example:**
```python
async def take_screenshot(
    url: str,
    width: int,
    height: int,
    selector_list: list[str],
    output: str,
) -> bool:
    """Take a screenshot of a webpage"""
    return True
```

### Naming Conventions
- **Variables/Functions:** `snake_case`
- **Classes:** `PascalCase`
- **Constants:** `UPPER_SNAKE_CASE`
- **Private methods:** `_leading_underscore`
- **Dunder methods:** `__magic_methods__`

**Example:**
```python
class S3Client:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._max_retries = 3
    
    async def upload_file(self, filepath: str, filename: Optional[str] = None) -> str:
        pass

MAX_FILE_SIZE_MB = 100
```

### Error Handling
- Use specific exception types (`HTTPException`, `ClientError`, etc.)
- Include meaningful error messages
- Use structured error responses for API endpoints
- Log errors using the configured console

**Example:**
```python
from fastapi import HTTPException
from botocore.exceptions import ClientError

async def get_file(self, filename: str):
    try:
        response = self.s3.get_object(Bucket=self.bucket, Key=filename)
        return response
    except ClientError as e:
        error_code = e.response.get("Error", {}).get("Code")
        if error_code == "NoSuchKey":
            raise HTTPException(status_code=404, detail="File not found")
        raise HTTPException(status_code=500, detail="S3 error occurred")
```

### Async/Await Patterns
- Use `async`/`await` for I/O operations (S3, HTTP, file operations)
- Use `asyncio.create_subprocess_exec()` for external commands
- Always handle async context managers properly

**Example:**
```python
async def convert_image(self, input_path: str, output_path: str) -> bool:
    cmd = ["convert", input_path, "-resize", "800x600", output_path]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode == 0
```

### Configuration & Settings
- Use `pydantic-settings` for configuration
- Environment variables should be `UPPER_SNAKE_CASE`
- Use `Field()` for default values and validation
- Support both `.env` file and environment variables

**Example:**
```python
from pydantic import Field
from pydantic_settings import BaseSettings

class Config(BaseSettings):
    aws_bucket_name: str = Field(default="screenshots")
    max_file_size_mb: int = Field(default=100)
    
    class Config:
        env_file = ".env"
        case_sensitive = False
```

### API Endpoint Patterns
- Use FastAPI route decorators (`@app.get`, `@app.post`, etc.)
- Use proper HTTP status codes
- Include request/response models for complex data
- Support both GET and HEAD where appropriate
- Add CORS headers for cross-origin requests

**Example:**
```python
@app.get("/shot/{filename}")
async def get_shot(
    request: Request,
    filename: str,
    url: str = Query(...),
    width: int = Query(default=800),
    height: int = Query(default=600),
) -> StreamingResponse:
    """Get a screenshot"""
    return StreamingResponse(
        content=image_data,
        media_type="image/webp",
        headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        },
    )
```

### File Organization
- **`shot_scraper_api/api/`**: FastAPI application and routes
- **`shot_scraper_api/cli/`**: Command-line interface
- **`shot_scraper_api/tui/`**: Terminal user interface
- **`shot_scraper_api/`**: Core utilities (config, s3, console)
- **`tests/`**: Test files (mirror source structure)

### Testing Guidelines
- Use `pytest` for testing
- Use `pytest-mock` for mocking external dependencies
- Test both success and error cases
- Use descriptive test names
- Mock S3 and browser operations in unit tests

**Example:**
```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_take_screenshot_success():
    with patch("pyppeteer.launch") as mock_launch:
        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_browser.newPage.return_value = mock_page
        mock_launch.return_value = mock_browser
        
        result = await take_screenshot("https://example.com", 800, 600, [], "/tmp/test.png")
        
        assert result is True
        mock_page.goto.assert_called_once()
```

### Documentation & Comments
- Use docstrings for all public functions and classes
- Follow Google-style or NumPy-style docstring format
- Include type hints in docstrings
- Add inline comments for complex logic
- Use `# TODO:` or `# FIXME:` for temporary notes

**Example:**
```python
def generate_filename(
    url: str, 
    width: int, 
    height: int, 
    format: str = "webp"
) -> str:
    """Generate a unique filename for a screenshot.
    
    Args:
        url: The URL to screenshot
        width: Image width in pixels
        height: Image height in pixels  
        format: Image format (webp, png, jpg)
        
    Returns:
        A unique filename string.
    """
    hash_input = f"{url}-{width}x{height}"
    filename_hash = hashlib.md5(hash_input.encode()).hexdigest()
    return f"{filename_hash}-{width}x{height}.{format}"
```

## Security Considerations

- Never log or expose AWS credentials
- Use environment variables for sensitive configuration
- Validate all user inputs in API endpoints
- Use path-style S3 addressing for MinIO compatibility
- Sanitize URLs to prevent SSRF attacks
- Limit file upload sizes

## Performance Guidelines

- Use S3 caching for generated screenshots
- Implement proper async/await patterns
- Use streaming responses for large files
- Configure appropriate browser timeouts
- Use connection pooling for S3 operations

## Common Patterns

### Singleton Config
```python
from functools import lru_cache

@lru_cache()
def get_config() -> Config:
    return Config()
```

### Async File Operations
```python
import aiofiles

async def read_file_async(filepath: str) -> str:
    async with aiofiles.open(filepath, 'r') as f:
        return await f.read()
```

### Error Response Helper
```python
def create_error_response(detail: str, status_code: int = 400):
    raise HTTPException(status_code=status_code, detail=detail)
```

Remember to run `hatch run lint-test` before committing changes to ensure code quality standards are met.