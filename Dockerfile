# OpenMontage — video creation & automated publishing pipeline
# Base: Node 22 (HyperFrames CLI) + Python 3 (tools/publishers) + ffmpeg + Chrome
FROM node:22-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PUPPETEER_SKIP_DOWNLOAD=1 \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium \
    NODE_PATH=/app/node_modules

# System deps: python, ffmpeg, chromium (multi-arch), curl, and jq
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv \
      ffmpeg \
      chromium \
      curl jq \
      ca-certificates fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps (layer-cached before source copy)
COPY requirements.txt requirements-publish.txt requirements-dev.txt ./
RUN pip3 install -r requirements.txt -r requirements-publish.txt -r requirements-dev.txt edge-tts>=7.2

# Node deps (HyperFrames CLI)
COPY package.json package-lock.json* ./
RUN npm install --omit=dev

# Claude Code CLI — drives the news selection / research pipeline
# (lib/claude_news_selector.py shells out to `claude --print`)
RUN npm install -g @anthropic-ai/claude-code

# Project source
COPY . .
ENV PYTHONPATH=/app

CMD ["bash"]
