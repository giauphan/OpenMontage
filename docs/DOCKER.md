# OpenMontage Docker Setup

## Mục đích

Docker image chứa đầy đủ môi trường chạy toàn bộ pipeline: TTS narration, HyperFrames render, và automated publishing.

## Yêu cầu host machine

- Docker Engine ≥ 24
- Docker Compose ≥ 2.20
- File `.env` đã được cấu hình (xem `.env.example`)

## Build & chạy

```bash
# Build image
docker compose build

# Chạy cron scheduler (YouTube + Meta publish tự động)
docker compose up -d scheduler

# Render video thủ công cho một project
docker compose run --rm worker bash -c "
  python3 /tmp/gen_narration.py && \
  ./node_modules/.bin/hyperframes render projects/<topic>/hyperframes projects/<topic>/renders/final_full_vi_9x16.mp4
"

# Chạy test suite
docker compose run --rm worker pytest tests/ -q
```

## Volumes

| Volume | Nội dung |
|--------|----------|
| `./projects` | Source compositions, audio, renders |
| `./config` | `publish_schedule.json` |
| `./credentials` | Google OAuth token, service-account JSON |

## Environment variables

Tất cả vars được inject từ `.env` — xem `.env.example` để biết danh sách đầy đủ.
