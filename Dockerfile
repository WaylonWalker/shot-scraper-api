FROM python:3.12-slim
ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    imagemagick \
    webp \
    # Dependencies for Chromium and Playwright
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libc6 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libexpat1 \
    libfontconfig1 \
    libgbm1 \
    libgcc1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libstdc++6 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxi6 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    lsb-release \
    wget \
    xdg-utils \
    # Additional dependencies for Playwright
    gstreamer1.0-libav \
    libatomic1 \
    libxslt1.1 \
    libvpx7 \
    libevent-2.1-7 \
    libopus0 \
    gstreamer1.0-plugins-base \
    libharfbuzz-icu0 \
    libenchant-2-2 \
    libsecret-1-0 \
    libhyphen0 \
    libmanette-0.2-0 \
    libnghttp2-14 \
    x264 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY pyproject.toml /app
COPY shot_scraper_api/__about__.py /app/shot_scraper_api/__about__.py
COPY README.md /app
RUN pip3 install --no-cache-dir --root-user-action=ignore --upgrade pip wheel
RUN pip3 install --no-cache-dir --root-user-action=ignore .

# Install Playwright browser
RUN playwright install chromium
RUN playwright install-deps

# Copy application code
COPY . /app

EXPOSE 5000

CMD ["uvicorn", "shot_scraper_api.api.app:app", "--host", "0.0.0.0", "--port", "5000"]
