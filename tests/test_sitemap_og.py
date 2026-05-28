from shot_scraper_api.sitemap_og import (
    build_og_page_url,
    build_og_shot_urls,
    collect_sitemap_og_shots,
    fetch_sitemap_urls,
)


def test_fetch_sitemap_urls_parses_namespace_xml(monkeypatch):
    xml_payload = b"""
    <?xml version="1.0" encoding="UTF-8"?>
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://go.waylonwalker.com/</loc></url>
      <url><loc>https://go.waylonwalker.com/about/</loc></url>
    </urlset>
    """

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        def read(self):
            return xml_payload

    def fake_urlopen(req, timeout):
        del req, timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert fetch_sitemap_urls(
        "https://go.waylonwalker.com/sitemap.xml", 30.0, "ua"
    ) == [
        "https://go.waylonwalker.com/",
        "https://go.waylonwalker.com/about/",
    ]


def test_build_og_page_url_appends_og_suffix():
    assert (
        build_og_page_url("https://go.waylonwalker.com/")
        == "https://go.waylonwalker.com/og/"
    )
    assert (
        build_og_page_url("https://go.waylonwalker.com/about/")
        == "https://go.waylonwalker.com/about/og/"
    )


def test_build_og_shot_urls_generates_both_sizes():
    assert build_og_shot_urls("https://go.waylonwalker.com/about/") == [
        "https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fgo.waylonwalker.com%2Fabout%2Fog%2F&height=600&width=1200&scaled_width=1200&scaled_height=600&format=jpg",
        "https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fgo.waylonwalker.com%2Fabout%2Fog%2F&height=640&width=1280&scaled_width=1280&scaled_height=640&format=jpg",
    ]


def test_collect_sitemap_og_shots_deduplicates_shots():
    page_urls = [
        "https://go.waylonwalker.com/about/",
        "https://go.waylonwalker.com/about/",
        "https://go.waylonwalker.com/",
    ]

    assert collect_sitemap_og_shots(page_urls) == [
        "https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fgo.waylonwalker.com%2Fabout%2Fog%2F&height=600&width=1200&scaled_width=1200&scaled_height=600&format=jpg",
        "https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fgo.waylonwalker.com%2Fabout%2Fog%2F&height=640&width=1280&scaled_width=1280&scaled_height=640&format=jpg",
        "https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fgo.waylonwalker.com%2Fog%2F&height=600&width=1200&scaled_width=1200&scaled_height=600&format=jpg",
        "https://shots.waylonwalker.com/shot/?url=https%3A%2F%2Fgo.waylonwalker.com%2Fog%2F&height=640&width=1280&scaled_width=1280&scaled_height=640&format=jpg",
    ]
