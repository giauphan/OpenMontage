# OpenMontage — video creation & automated publishing pipeline
# Base: Node 22 (HyperFrames CLI) + Python 3 (tools/publishers) + ffmpeg + Chrome
FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PUPPETEER_SKIP_DOWNLOAD=1 \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/google-chrome-stable \
    NODE_PATH=/app/node_modules

# System deps: python, ffmpeg, and Chrome runtime libraries for HyperFrames render
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv \
      ffmpeg \
      ca-certificates wget gnupg fonts-liberation \
      libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
      libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
      libpango-1.0-0 libcairo2 libatspi2.0-0 \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps (layer-cached before source copy)
COPY requirements.txt requirements-publish.txt ./
RUN pip3 install -r requirements.txt -r requirements-publish.txt edge-tts>=7.2

# Node deps (HyperFrames CLI)
COPY package.json package-lock.json* ./
RUN npm install --omit=dev

# Project source
COPY . .

CMD ["bash"]
