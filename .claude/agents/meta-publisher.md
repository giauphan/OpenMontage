# Meta Publisher Agent

## Purpose
Handles Facebook Page and Instagram Business Reels publishing via Meta Graph API. Used by `publish_manual_video.py` and `publish_active_projects.py`.

## Token Lifecycle
- `TOKEN_FACEBOOK` is a Meta Graph API User Access Token; it expires/revokes periodically.
- When Instagram or Facebook publish fails with `HTTP Error 400: Bad Request`, the root cause is always token expiry — not code. Renew at Meta Business Suite > Tools > Tokens.
- `publish_manual_video.py` preflight gates each platform independently; a failed Meta token never blocks YouTube.

## Publishing Contract
- Facebook: uploads video to `page_id`, returns `facebook_post_id`.
- Instagram: uploads via Cloudflare R2 temp URL, creates media container, returns `instagram_media_id`.
- Both require `page_id` (Facebook Page) and a valid `TOKEN_FACEBOOK`.
- `MULTI_PLATFORM=1` enables YouTube + Instagram + Facebook; default is YouTube only.

## Server Control Rules
- This agent runs headless on `sandbox-video` via SSH from Hermes/Claude Code.
- No interactive prompts; use `--dry-run` to validate before upload.
- On failure: record `failed` status in Firebase, log error, continue other platforms.
- After token renewal, rerun `scripts/publish_manual_video.py <project> --date YYYY-MM-DD` for the affected platform only.
