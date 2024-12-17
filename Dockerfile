FROM python:3.12-slim
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app
RUN pip install shot-scraper
RUN playwright install
RUN playwright install-deps
RUN apt update && \
    apt install imagemagick webp -y && \
    rm -rf /var/lib/apt/lists/*
COPY pyproject.toml /app
COPY shot_scraper_api/__about__.py /app/shot_scraper_api/__about__.py
COPY README.md /app
RUN pip3 install --no-cache-dir --root-user-action=ignore --upgrade pip wheel
RUN pip3 install --no-cache-dir --root-user-action=ignore .
COPY . /app
RUN pip3 install --no-cache-dir --no-deps --root-user-action=ignore .

EXPOSE 5000

ENTRYPOINT shot-scraper-api run --env prod
