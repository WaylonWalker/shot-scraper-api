from shot_scraper_api.reader_shots import (
    ReaderPageParser,
    build_trigger_shot_url,
    crawl_reader_pages,
)


def test_reader_page_parser_collects_reader_pages_and_shot_images():
    parser = ReaderPageParser(
        page_url="https://go.waylonwalker.com/reader/",
        shots_host="shots.waylonwalker.com",
    )

    parser.feed(
        """
        <html>
          <body>
            <img src="https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fexample.com&height=160&width=240&scaled_width=240&scaled_height=160&format=jpg">
            <img src="https://cdn.example.com/thumb.jpg">
            <a href="/reader/page/2/">Older</a>
            <a href="https://go.waylonwalker.com/reader/page/3/">Page 3</a>
            <a href="https://example.com/not-reader">External</a>
          </body>
        </html>
        """
    )

    assert parser.shot_image_urls == [
        "https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fexample.com&height=160&width=240&scaled_width=240&scaled_height=160&format=jpg"
    ]
    assert parser.external_image_urls == ["https://cdn.example.com/thumb.jpg"]
    assert parser.reader_page_urls == [
        "https://go.waylonwalker.com/reader/page/2/",
        "https://go.waylonwalker.com/reader/page/3/",
    ]


def test_build_trigger_shot_url_preserves_query():
    image_url = (
        "https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fexample.com"
        "&height=160&width=240&scaled_width=240&scaled_height=160&format=jpg"
    )

    assert build_trigger_shot_url(image_url) == (
        "https://shots.waylonwalker.com/trigger/shot?"
        "url=https%3A%2F%2Fexample.com&height=160&width=240&scaled_width=240"
        "&scaled_height=160&format=jpg"
    )


def test_crawl_reader_pages_deduplicates_pages_and_images(monkeypatch):
    pages = {
        "https://go.waylonwalker.com/reader/": """
        <img src="https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fexample.com&height=160&width=240&scaled_width=240&scaled_height=160&format=jpg">
        <a href="/reader/page/2/">Older</a>
        """,
        "https://go.waylonwalker.com/reader/page/2/": """
        <img src="https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fexample.com&height=160&width=240&scaled_width=240&scaled_height=160&format=jpg">
        <img src="https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fexample.org&height=160&width=240&scaled_width=240&scaled_height=160&format=jpg">
        <a href="/reader/">Newer</a>
        """,
    }

    def fake_fetch_text(url: str, timeout: float, user_agent: str) -> str:
        del timeout, user_agent
        return pages[url]

    monkeypatch.setattr("shot_scraper_api.reader_shots.fetch_text", fake_fetch_text)

    result = crawl_reader_pages(
        start_url="https://go.waylonwalker.com/reader/",
        timeout=10.0,
        user_agent="test-agent",
        shots_host="shots.waylonwalker.com",
    )

    assert result.page_urls == [
        "https://go.waylonwalker.com/reader/",
        "https://go.waylonwalker.com/reader/page/2/",
    ]
    assert result.shot_image_urls == [
        "https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fexample.com&height=160&width=240&scaled_width=240&scaled_height=160&format=jpg",
        "https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fexample.org&height=160&width=240&scaled_width=240&scaled_height=160&format=jpg",
    ]
