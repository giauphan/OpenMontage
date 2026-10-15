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
# cron is baked in so the scheduler does not depend on runtime apt/network.
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv \
      ffmpeg \
      chromium \
      curl jq \
      cron \
      ca-certificates fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python deps (layer-cached before source copy)
COPY requirements.txt requirements-publish.txt requirements-dev.txt ./
RUN pip3 install -r requirements.txt -r requirements-publish.txt -r requirements-dev.txt edge-tts>=7.2

# Node deps (HyperFrames CLI)
COPY package.json package-lock.json* ./
RUN npm install --omit=dev

# Codex CLI — drives news selection / research / validation pipeline
RUN npm install -g @openai/codex

# Project source
COPY . .
ENV PYTHONPATH=/app

# Make validation scripts executable
RUN chmod +x scripts/codex_agent_validation.py scripts/validate_render_quality.py scripts/validate_publish_metadata.py

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]

