## 0.0.35

- reduced media wait time.

## 0.0.34

- added: `theme` query parameter (`light` or `dark`) to `/shot`, `/shot/async`, `/shot/blocking`, `/trigger/shot`, and `DELETE /shot` filename generation for deterministic theme-specific cache keys
- changed: screenshot cache key generation now includes theme, allowing separate immutable dark and light variants for the same URL and dimensions
- changed: queue payloads and dedupe checks now include theme so worker jobs remain consistent across API, queue, and processor paths
- improved: browser launch now includes autoplay-friendly Chromium flags (`--autoplay-policy=no-user-gesture-required`, `--mute-audio`) to improve initial video frame capture reliability
- improved: screenshot rendering now emulates `prefers-color-scheme` and applies document color scheme hints before capture when `theme` is provided
- improved: media readiness wait extended to 10s max and video readiness logic now accepts any visible video with frame data, reducing false timeouts when one embed stalls

## 0.0.33

- changed: `GET /shot?url=...` now defaults to blocking image responses for legacy OG/image consumers
- added: `GET /shot/async` and `HEAD /shot/async` for explicit async JSON queue status behavior
- added: `mode=async` query option on `/shot` to force async JSON behavior when needed
- added: `DELETE /shot/{filename}` and `DELETE /shot?url=...` to remove existing generated shots from object storage
- added: richer `/queue/stats` metrics including average processing duration, success rate, queue ages, and completions in the last hour
- changed: Redis queue stats now use Redis-backed aggregate counters for faster stats responses
- changed: JSON/status endpoints now send explicit no-store cache headers so Cloudflare only caches image responses
- changed: image responses now include CDN-friendly cache headers (`s-maxage`, `immutable`) for edge caching
- improved: screenshot capture now waits for visible videos to have actual frame data before capture to reduce blank clips

## 0.0.32

- fix: wait for visible media before capture to reduce incomplete screenshots
- added: pre-capture wait for visible in-viewport images to finish loading
- added: pre-capture font readiness wait for more stable text rendering
- changed: video readiness wait now uses a bounded shared media timeout

## 0.0.31

- feat: add blocking image endpoint for crawler and OG consumers
- added: `GET /shot/blocking` and `HEAD /shot/blocking` to queue, wait, and return image bytes
- added: `wait` query parameter (default `30000`, max `120000`) for blocking timeout control
- changed: shared format/version/timeout parsing and image header helpers in API routes
- maintained: existing `/shot` async JSON queue behavior for current clients

## 0.0.30

- feat: add build trigger mechanism for async screenshot generation
- added: `POST /trigger/shot` endpoint to queue screenshots with priority levels (0-10)
- added: `GET /job/{job_id}` endpoint to check individual job status
- added: `GET /queue/stats` endpoint to monitor queue statistics
- added: background task processor that handles queued screenshots asynchronously
- added: enhanced `HEAD /shot/` endpoint with `X-Screenshot-Status` header
- added: priority-based job processing (higher priority jobs processed first)
- added: persistent job queue using diskcache (survives server restarts)
- added: duplicate detection - won't re-queue existing screenshots
- added: automatic cleanup of old completed/failed jobs (24 hours)
- added: comprehensive build process integration with fast response times
- refactored: screenshot generation logic moved to separate module to avoid circular imports

## 0.0.29

- feat: support versions, tack `?v=1` for example to get a new version of your
  screenshot, versions will be persisted and immutable.
- added: version parameter validation (positive integers only)
- changed: cache key generation now includes version in MD5 hash for unique filenames
- maintained: full backward compatibility - no version parameter works exactly like before

## 0.0.28

- fix: signal desktop preview fails due to missing HEAD request support
- feat: support HEAD requests to /shot/

## 0.0.27

- feat: support `?format=jpg`

## 0.0.26

- fix: browser not closing on failure

## 0.0.18

- add emoji font support

## 0.0.17

- fix presigned url set content type to image/webp not image/web

## 0.0.16

- swap playwright out for the working pypeteer

## 0.0.15 **broken**

- remove broken minio import

## 0.0.14 **broken**

- cleanup config
- remove minio from requirements
- add CACHE_DIR config

## 0.0.13 **broken**

- add an asycnio.sleep for animations to finish

## 0.0.12 **broken**

- better wait for animations to finish

## 0.0.11 **broken**

- fix s3 file upload

## 0.0.10 **broken**

- use presigned urls instead of serving static files

## 0.0.9 **broken**

- fix dockerfile python install missing dependencies
- request time is now around 2.5s in prod

## 0.0.8 **broken**

- run playwright installer in dockerfile

## 0.0.8 **broken**

- pyppeteer appears to be deprecated and caused 12s request time in prod
- use playwright instead, request times drop to 1 - 1.5s locally

## 0.0.8 **broken**

- use pyppeteer instead of shot_scraper
- request time drops from 6.5s to 2.5s

## 0.0.5

- fix broken import

## 0.0.4

- add favicon.ico as a route

## 0.0.3

- open up CORS, maybe this fixes signal

## 0.0.2

- fix dockerfile

## 0.0.1

- make content type selectable
- add favicon.ico

## 0.0.0

init
