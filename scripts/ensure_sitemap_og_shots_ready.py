#!/usr/bin/env python3
"""Ensure sitemap OG screenshots linked to shots.waylonwalker.com are ready."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from shot_scraper_api.sitemap_og import main as sitemap_main

    sitemap_main()


if __name__ == "__main__":
    main()
