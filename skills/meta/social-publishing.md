# Social Publishing — Auto-Publish Videos to Every Platform

## 3-Tier Multi-Format Render & Publishing Matrix

OpenMontage renders 3 video versions per topic to optimize reach on all major social platforms:

1. **Version 1: 16:9 Landscape Full (120s, 1920x1080)**:
   - Target Platform: **YouTube Long-Form Video** (ensures standard video player placement, avoiding Shorts classification).
   - Tool: `youtube_publisher`

2. **Version 2: 9:16 Vertical Short (~60s, 1080x1920 / 1080x1350)**:
   - Target Platforms: **YouTube Shorts**, **Instagram Reels** (short high-pacing hook clips).
   - Tools: `youtube_publisher` (Shorts auto-classification), `meta_publisher` (Instagram Reels via R2 temp upload)

3. **Version 3: 9:16 Vertical Full (120s, 1080x1920)**:
   - Target Platforms: **Facebook Reels**, **TikTok** (full-length vertical content).
   - Tools: `meta_publisher` (Facebook Page Reels), `tiktok_publisher` (TikTok Creator Studio)

## When to Use

After a video render is complete (`render_report` exists), use this skill to automatically distribute the final video to all configured social platforms: YouTube, Facebook Page, Instagram Reels, and TikTok.

## Tool Inventory

Every publisher is a registered `BaseTool` with `capability="publish"`. Query at runtime:

```bash
python -c "from tools.tool_registry import registry; import json; registry.discover(); print(json.dumps(registry.capability_catalog().get('publish'), indent=2))"
```

| Tool | Platform | Method | Credentials Needed |
|------|----------|--------|-------------------|
| `youtube_publisher` | YouTube / Shorts | YouTube Data API v3 | `YOUTUBE_CLIENT_SECRET_FILE` (+ OAuth token auto-saved at `~/.openmontage/youtube_token.json`) |
| `meta_publisher` | Facebook Page + Instagram Reels | Meta Graph API v26 | `TOKEN_FACEBOOK` (+ `CLOUDFLARE_R2_*` for Instagram temp hosting) |
| `tiktok_publisher` | TikTok | Playwright browser automation | `~/.openmontage/tiktok_cookies.json` |
| `export_bundle` | Local packaging | Filesystem copy | none |

## Publish Flow

1. Build localized metadata from the final script, not the original proposal. A Vietnamese video must get Vietnamese title/description/captions.
2. Always run `export_bundle` first for local handoff.
3. Then run configured publishers:
   - YouTube: `youtube_publisher`
   - Facebook + Instagram: `meta_publisher`
   - TikTok: `tiktok_publisher`
4. Combine tool outputs into one `publish_log` with one entry per platform.
5. If any configured publisher fails, keep successful entries and add failed entry/error for that platform.

## YouTube

- Endpoint: YouTube Data API v3 `videos.insert`.
- First auth saves OAuth token at `~/.openmontage/youtube_token.json`.
- YouTube auto-classifies vertical videos ≤3 minutes as Shorts. There is no API flag for Shorts.
- Use horizontal 16:9 if the user explicitly wants regular long-form YouTube placement.

## Meta (Facebook Page + Instagram)

- `meta_publisher` gets Page access token from `TOKEN_FACEBOOK`.
- Facebook Page video upload uses Graph API `/{page_id}/videos`.
- **Facebook Format**: Pass `final_full_vi.mp4` (120s Full Video) so Facebook Page receives the full video post/reel, matching YouTube long-form content.
- **Instagram Reels Format**: Pass `final_full_vi.mp4` or `final_full_vi_reels.mp4` via Cloudflare R2 temporary URL.
- Instagram Graph API requires a public `video_url`. `meta_publisher` uploads a temporary copy to Cloudflare R2, uses the R2 public URL for Instagram, then deletes the R2 object in `finally` after success or failure.
- Required env vars:
  - `TOKEN_FACEBOOK`
  - `CLOUDFLARE_R2_KEY_ID`
  - `CLOUDFLARE_R2_SERECT` (spelled this way in current `.env`)
  - `CLOUDFLARE_R2_ENDPOINT`
  - `CLOUDFLARE_R2_ENDPOINT_public`
  - `CLOUDFLARE_R2_BUCKET_NAME` (defaults to `open-montage` if omitted)

## TikTok

- `tiktok_publisher` uses Playwright + Google Chrome + cookies.
- Cookie file: `~/.openmontage/tiktok_cookies.json`.
- It supports Cookie-Editor list JSON and Playwright storage_state JSON.
- TikTok may block datacenter/headless sessions; official Content Posting API is more reliable when available.

## Video Compliance for Reels

For Instagram Reels, encode to:

```bash
ffmpeg -y -i input.mp4 \
  -c:v libx264 -profile:v high -level 4.0 -pix_fmt yuv420p -r 30 \
  -b:v 2500k -maxrate 2500k -bufsize 5000k \
  -c:a aac -b:a 192k -movflags +faststart \
  -vf "scale=1080:1350:force_original_aspect_ratio=decrease,pad=1080:1350:(ow-iw)/2:(oh-ih)/2,setsar=1" \
  instagram_reels.mp4
```

## Pitfalls

- **Language mismatch**: Metadata language must match video language.
- **YouTube Shorts confusion**: vertical ≤3min becomes Shorts automatically; API is not wrong.
- **Meta token expiry**: `OAuthException` + `error_subcode: 463` means token expired.
- **Instagram `2207076`**: Meta could not ingest media. Check tester acceptance, public URL, video compliance, and wait if new tester/app state was just changed.
- **R2 cleanup**: never leave temporary video objects behind. Delete object after Instagram attempt regardless of result.
- **R2 ListBuckets AccessDenied**: expected for scoped tokens; test with known bucket and `put_object`.