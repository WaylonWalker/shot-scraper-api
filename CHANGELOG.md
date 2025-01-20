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
