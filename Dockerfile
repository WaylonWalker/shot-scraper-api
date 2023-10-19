FROM python:3.12-slim
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app
COPY pyproject.toml /app
COPY shot_scraper_api/__about__.py /app/shot_scraper_api/__about__.py
COPY README.md /app
RUN pip3 install --no-cache-dir --root-user-action=ignore --upgrade pip
RUN pip3 install --no-cache-dir --root-user-action=ignore .
COPY . /app
RUN pip3 install --no-cache-dir --root-user-action=ignore .
RUN playwright install
RUN playwright install-deps
RUN apt update && \
    apt install imagemagick webp -y && \
    rm -rf /var/lib/apt/lists/*

EXPOSE 5000

ENTRYPOINT shot-scraper-api api run
