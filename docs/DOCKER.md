# OpenMontage Docker Setup

## Mục đích

Docker image chứa đầy đủ môi trường chạy toàn bộ pipeline:
- **TTS narration**: Edge-TTS / Google TTS
- **HyperFrames render**: Chromium headless + Node.js 22
- **NewsNow + Claude AI pipeline**: Ingest NewsNow candidates, dùng Claude CLI để chọn bài & viết kịch bản tự động
- **Automated publishing**: Cron scheduler cho YouTube Shorts & Meta Reels

## Yêu cầu host machine

- Docker Engine ≥ 24
- Docker Compose ≥ 2.20
- File `.env` đã được cấu hình (xem `.env.example`)

---

## 1. Setup Claude CLI login trong Docker

NewsNow pipeline sử dụng `claude` CLI (`lib/claude_news_selector.py`) để chọn tin tức và tạo kịch bản AI.

### Cách A: Tận dụng session login có sẵn trên host (Tự động)
`docker-compose.yml` đã mount sẵn `~/.claude.json` và `~/.claude` từ máy host vào container.
Nếu host đã đăng nhập `claude`, container sẽ **tự nhận login session** mà không cần đăng nhập lại:

```bash
# Kiểm tra Claude CLI trong container
docker compose run --rm worker claude --version
```

### Cách B: Đăng nhập trực tiếp trong container (Nếu máy mới)
```bash
# Mở terminal container
docker compose run --rm worker bash

# Đăng nhập Claude CLI
claude login
```

---

## 2. Setup NewsNow Video Generation Pipeline

```bash
# 1. Ingest tin tức từ NewsNow feed và chạy Claude AI chọn bài + tạo kịch bản
docker compose run --rm worker python3 tools/news/news_pipeline_cli.py --input feed.json --output-dir projects/newsnow-latest

# 2. Render video NewsNow
docker compose run --rm worker bash -c "
  python3 tools/news/generate_narration.py --project projects/newsnow-latest && \
  ./node_modules/.bin/hyperframes render projects/newsnow-latest/hyperframes projects/newsnow-latest/renders/final_full_vi_9x16.mp4
"
```

---

## 3. Build & Chạy Cron Scheduler

```bash
# Build image
docker compose build

# Chạy cron scheduler tự động (YouTube 01:00 UTC / Meta 01:30 UTC)
docker compose up -d scheduler

# Chạy test suite
docker compose run --rm worker pytest tests/ -q
```

---

## Volumes Mount

| Volume | Nội dung |
|--------|----------|
| `./projects` | Source compositions, audio, renders |
| `./config` | `publish_schedule.json` |
| `./credentials` | Google OAuth token, service-account JSON |
| `~/.claude` | Session login Claude CLI từ host machine |
