from shot_scraper_api.api.app import (
    _format_to_media_type,
    _image_headers,
    _status_headers,
)


class TestFormatToMediaType:
    def test_jpg_maps_to_image_jpeg(self):
        assert _format_to_media_type("jpg") == "image/jpeg"

    def test_jpeg_maps_to_image_jpeg(self):
        assert _format_to_media_type("jpeg") == "image/jpeg"

    def test_png_maps_to_image_png(self):
        assert _format_to_media_type("png") == "image/png"

    def test_webp_maps_to_image_webp(self):
        assert _format_to_media_type("webp") == "image/webp"


class TestImageHeaders:
    def test_jpg_format_uses_image_jpeg_content_type(self):
        headers = _image_headers("jpg")
        assert headers["Content-Type"] == "image/jpeg"

    def test_jpeg_format_uses_image_jpeg_content_type(self):
        headers = _image_headers("jpeg")
        assert headers["Content-Type"] == "image/jpeg"

    def test_png_format_uses_image_png_content_type(self):
        headers = _image_headers("png")
        assert headers["Content-Type"] == "image/png"

    def test_webp_format_uses_image_webp_content_type(self):
        headers = _image_headers("webp")
        assert headers["Content-Type"] == "image/webp"


class TestStatusHeaders:
    def test_jpg_format_uses_image_jpeg_content_type(self):
        headers = _status_headers("jpg", "queued")
        assert headers["Content-Type"] == "image/jpeg"

    def test_jpeg_format_uses_image_jpeg_content_type(self):
        headers = _status_headers("jpeg", "processing")
        assert headers["Content-Type"] == "image/jpeg"
