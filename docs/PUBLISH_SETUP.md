# OpenMontage — Automated Publishing Setup Guide

This guide explains how to set up the multi-platform publishing flow (YouTube Shorts, Facebook Reels, Instagram Reels, Firestore dedup) on a new server or environment.

---

## 1. Architecture Overview

```
                        ┌─────────────────────────────────────┐
                        │    config/publish_schedule.json     │
                        │  (active projects, time slots, IDs) │
                        └──────────────────┬──────────────────┘
                                           │
         ┌─────────────────────────────────┼─────────────────────────────────┐
         ▼                                 ▼                                 ▼
┌──────────────────┐             ┌──────────────────┐             ┌──────────────────┐
│  YouTube API v3  │             │  Meta Graph API  │             │  Cloudflare R2   │
│  (YT Shorts 120s)│             │ (FB Reels 120s)  │             │(Temp IG video url│
└────────┬─────────┘             └────────┬─────────┘             └────────┬─────────┘
         │                                │                                │
         └────────────────────────────────┼────────────────────────────────┘
                                          ▼
                         ┌─────────────────────────────────┐
                         │   Firebase Firestore Database   │
                         │   collection: openmontage_...   │
                         │   (6-layer uniqueness claim)    │
                         └─────────────────────────────────┘
```

### Key Rules
- **Daily Limit**: 3 videos per day per platform maximum.
- **Shorts-Only Policy**: 120s vertical (9:16) for YouTube Shorts and Facebook Reels; 60s vertical for Instagram Reels. 16:9 Long flow is deprecated.
- **Atomic Dedup**: Every publish attempt claims Firestore locks for `topic`, `title`, `source_topic`, `source_path`, `source_visual`, `source_sha256`. Duplicate uploads are rejected automatically.

---

## 2. Requirements

1. Python dependencies:
   ```bash
   pip install -r requirements.txt
   pip install -r requirements-publish.txt
   ```
2. Required API Credentials:
   - **YouTube**: Google Cloud Console → YouTube Data API v3 enabled → OAuth 2.0 Client ID (Desktop App). Download as `client_secret_...json`.
   - **Meta**: Meta for Developers → App with `pages_read_engagement`, `pages_manage_posts`, `instagram_basic`, `instagram_content_publish`. Generate long-lived User Access Token.
   - **Firebase**: GCP Service Account JSON key with Firestore read/write access.
   - **Cloudflare R2**: Bucket for temporary Instagram media hosting + API key/secret.

---

## 3. Environment Variables (`.env`)

Copy `.env.example` to `.env` and configure:

```bash
# Meta
TOKEN_FACEBOOK="EAAG..."
FB_PAGE_ID="1183103681563663"
IG_ACCOUNT_ID="17841434265610775"

# YouTube
YOUTUBE_CLIENT_SECRET_FILE="/path/to/client_secret.json"

# Firebase (inline JSON string or path to JSON file)
FIREBASE_SERVICE_ACCOUNT='{"type":"service_account",...}'

# Cloudflare R2
CLOUDFLARE_R2_KEY_ID="your_key_id"
CLOUDFLARE_R2_SECRET="your_secret"
CLOUDFLARE_R2_ENDPOINT="https://<account_id>.r2.cloudflarestorage.com"
CLOUDFLARE_R2_BUCKET_NAME="store-instagram"

# Optional overrides
PUBLISH_TZ="Asia/Jakarta"
```

---

## 4. Configuration (`config/publish_schedule.json`)

Controls active projects and scheduling slots:

```json
{
  "version": "1.0",
  "timezone": "Asia/Jakarta",
  "meta": {
    "page_id": "1183103681563663",
    "ig_account_id": "17841434265610775"
  },
  "youtube": {
    "account": "primary"
  },
  "slots": {
    "fb_slots_wib": ["12:00", "14:00", "16:00"],
    "yt_slots_wib": ["09:15", "14:15", "21:15"]
  },
  "active_projects": [
    "quantum-ai-chips-2026",
    "robotics-dark-factories-2026"
  ]
}
```

To change which videos get published daily, update `active_projects`.

---

## 5. Project Metadata Requirements

Every project in `projects/<project_id>/` must contain `publish_metadata.json`:

```json
{
  "id": "quantum-ai-chips-2026",
  "topic": "Quantum AI Chips 2026",
  "title": "Chip bán dẫn AI lượng tử 2026...",
  "description": "Full video description...",
  "yt_shorts": "projects/quantum-ai-chips-2026/renders/final_reels_vi_9x16.mp4",
  "ig_reels": "projects/quantum-ai-chips-2026/renders/final_reels_vi_9x16.mp4",
  "fb_video": "projects/quantum-ai-chips-2026/renders/final_full_vi_9x16.mp4"
}
```

---

## 6. Command-Line Usage

### Manual Single-Project Run (Dry-Run & Live)
```bash
# Test without uploading:
python3 scripts/publish_manual_video.py projects/quantum-ai-chips-2026 --dry-run

# Live upload:
python3 scripts/publish_manual_video.py projects/quantum-ai-chips-2026
```

### Schedule Today's Queued Platform Slots
```bash
# Schedule today's queued projects across enabled platform routes:
./scripts/run_youtube_schedule.sh

# Schedule specific date:
./scripts/run_youtube_schedule.sh 2026-08-17
```

`run_youtube_schedule.sh` delegates to the native scheduler, which handles
enabled YouTube, Instagram, Facebook, and TikTok routes from the queued project
configuration. It does not require the removed Meta-only wrapper.

---

## 7. Cron Setup on a New Server

Create `logs/` directory and install the crontab:

```bash
mkdir -p logs
crontab deploy/openmontage.cron
```

Verify cron service is running:
```bash
systemctl status cron
crontab -l
```

Cron runs automatically every morning:
- **08:00 WIB**: Schedules YouTube Shorts for all `active_projects`.
- **08:30 WIB**: Schedules Facebook Reels + publishes Instagram Reels for all `active_projects`.
