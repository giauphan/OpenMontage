# OpenMontage Docker Setup

## Mục đích

Docker image chứa đầy đủ môi trường chạy toàn bộ pipeline:
- **TTS narration**: Edge-TTS / Google TTS
- **HyperFrames render**: Chromium headless + Node.js 22
- **NewsNow + Codex AI pipeline**: Ingest NewsNow candidates, dùng OpenAI Codex CLI (`@openai/codex`) để chọn bài & viết kịch bản tự động
- **Automated publishing**: Cron scheduler cho YouTube Shorts & Meta Reels

## Yêu cầu host machine

- Docker Engine ≥ 24
- Docker Compose ≥ 2.20
- File `.env` đã được cấu hình (xem `.env.example`)

---

## 1. Setup Codex CLI credentials trong Docker

NewsNow pipeline sử dụng `@openai/codex` CLI để chọn tin tức, tạo kịch bản AI và kiểm tra chất lượng video.

`docker-compose.yml` mount thư mục `~/.codex` từ máy host vào `/etc/codex_source:ro`. Container entrypoint (`/entrypoint.sh`) sẽ tự động khởi tạo runtime profiles (`/root/.codex_pipeline` và `/home/node/.codex_pipeline`) một cách an toàn và nhất quán trước khi chạy bất kỳ tiến trình nào.

### Cấu hình `~/.codex` trên máy Host

Tạo thư mục `~/.codex` trên máy host và chuẩn bị 2 file:

1. **`~/.codex/auth.json`**:
```json
{
  "OPENAI_API_KEY": "sk-your-openai-api-key"
}
```

2. **`~/.codex/config.toml`**:
```toml
model_provider = "openai"
```

Phân quyền bảo mật cho thư mục trên host:
```bash
chmod 700 ~/.codex
chmod 600 ~/.codex/*
```

### Kiểm tra Codex CLI trong container

```bash
docker compose run --rm worker codex --version
```

---

## 2. Setup NewsNow Video Generation Pipeline

```bash
# 1. Ingest tin tức từ NewsNow feed và chạy Codex AI chọn bài + tạo kịch bản
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
| `~/.codex` | Session login & credentials cho Codex CLI (`auth.json`, `config.toml`) |

