# Publish Director — Explainer Pipeline

## When to Use

You are the Publisher for a generated explainer video. You have a `render_report` with the final video file. Your job is to prepare the video for distribution: generate SEO metadata, create thumbnails, package exports, and **automatically publish to YouTube, Facebook Page, Instagram Reels, and TikTok**.

This is where a great video reaches its audience. Without proper metadata and packaging, even the best content gets buried.

## Prerequisites

| Layer | Resource | Purpose |
|-------|----------|---------|
| Schema | `schemas/artifacts/publish_log.schema.json` | Artifact validation |
| Prior artifacts | `state.artifacts["compose"]["render_report"]`, `state.artifacts["proposal"]["proposal_packet"]`, `state.artifacts["research"]["research_brief"]` | Video file and original proposal |
| Playbook | Active style playbook | Visual style for thumbnail |
| **Social Platforms** | `.env` with `TOKEN_FACEBOOK`, `YOUTUBE_CLIENT_SECRET_FILE`, `CLOUDFLARE_R2_*` | Auto-publish to YouTube, Facebook, Instagram, TikTok |

## Process

### Step 1: Gather Context

Collect everything needed for metadata:
- **Proposal packet**: title, hook, key points, target platform, tone
- **Render report**: output path, duration, resolution
- **Script**: section summaries for description/chapters

### Step 2: Generate SEO Metadata

**Title** (max 60 characters for YouTube):
- Include the primary keyword from the proposal packet
- Lead with a hook or number
- Avoid clickbait but be compelling
- Examples: "Vector Databases Explained in 60 Seconds" > "About Vector Databases"

**Description** (first 150 chars are critical — shown in search):
- Opening line: restate the hook with the main value proposition
- Body: key topics covered, with relevant keywords naturally included
- Chapters: timestamp markers for each major section (from script sections)
- Call to action: subscribe/like/follow
- Links: relevant resources mentioned in the video

**Tags/Keywords** (platform-dependent):
- 5-10 specific tags derived from proposal packet's key_points
- Mix broad and specific: "machine learning" + "vector database tutorial"
- Include the topic, format ("explainer"), and related terms

**Hashtags** (for social platforms):
- 3-5 relevant hashtags
- Mix trending and niche

### Step 3: Generate Thumbnail Concept

Describe a thumbnail that:
1. Uses the playbook's visual style
2. Features the video's core concept visually
3. Includes 3-5 words of text (the hook or key stat)
4. Has high contrast and is readable at small sizes
5. Uses the playbook's accent colors for text

```json
{
  "thumbnail": {
    "concept": "Split screen: left side shows slow SQL query (red X), right shows fast vector search (green check). Large text: '100x FASTER'",
    "text_overlay": "100x FASTER",
    "style_notes": "Use playbook accent colors, bold Inter font, dark background"
  }
}
```

*Note: Actual thumbnail generation happens via image_selector if available, otherwise it's a concept for manual creation.*

### Step 4: Create Chapter Markers

From the script sections, generate YouTube-style chapters:

```
0:00 - Introduction
0:15 - What are Vector Databases?
0:45 - How Embeddings Work
1:20 - The Search Algorithm
1:55 - Real-World Examples
2:30 - When to Use Vector DBs
```

Each chapter maps to a script section's `start_seconds`.

### Step 5: Package Export

Use the `export_bundle` tool (capability `publish`) to do the packaging deterministically — pass it the final `video_path` (from `render_report`), the `title`, and the metadata you prepared (`description`, `tags`, `hashtags`, `chapters`, optional `subtitles_path` and `thumbnail_path`/`thumbnail_concept`).

It produces this structure:

```
exports/
  <project_name>/
    video/
      output.mp4            # Final rendered video (subtitles.srt alongside if provided)
    metadata/
      metadata.json         # All SEO metadata
      chapters.txt          # Chapter markers
      description.txt       # Ready-to-paste description (+ chapters)
      tags.txt              # One tag per line
    thumbnails/
      concept.json          # Thumbnail concept (or the copied thumbnail image)
```

### Step 6: Auto-Publish to Social Platforms

**YouTube** (via `youtube_publisher`):
- Uploads directly to YouTube/Shorts using YouTube Data API v3
- Uses OAuth token stored at `~/.openmontage/youtube_token.json`
- Supports title, description, tags, privacy status, thumbnail

**Facebook Page** (via `meta_publisher`):
- Uploads to Facebook Page as Reels or standard video
- Uses Meta Graph API with `TOKEN_FACEBOOK`
- Supports caption, hashtags

**Instagram Reels** (via `meta_publisher`):
- Uploads to connected Instagram Business Account
- Uses temporary Cloudflare R2 hosting for video URL
- Automatically cleans up R2 file after upload
- Requires `CLOUDFLARE_R2_*` environment variables

**TikTok** (via `tiktok_publisher`):
- Uploads to TikTok Creator Studio via browser automation
- Uses Playwright with Google Chrome
- Requires TikTok cookies stored at `~/.openmontage/tiktok_cookies.json`

### Step 7: Build Publish Log

The publish tools return a schema-valid `publish_log` — persist that directly rather than hand-building one. The shape it returns:

```json
{
  "version": "1.0",
  "entries": [
    {
      "platform": "youtube",
      "status": "published",
      "url": "https://youtu.be/wc4yDSlHclo",
      "video_id": "wc4yDSlHclo",
      "visibility": "unlisted",
      "timestamp": "2026-01-15T10:30:00+00:00",
      "metadata_used": {
        "title": "Vector Databases Explained in 60 Seconds",
        "description": "What vector databases are and when to use them."
      }
    },
    {
      "platform": "facebook",
      "status": "published",
      "video_id": "1584367956398742",
      "url": "https://facebook.com/1183103681563663/videos/1584367956398742",
      "timestamp": "2026-01-15T10:30:00+00:00",
      "metadata_used": {
        "description": "What vector databases are and when to use them."
      }
    },
    {
      "platform": "instagram",
      "status": "published",
      "video_id": "18089203247142188",
      "timestamp": "2026-01-15T10:30:00+00:00",
      "metadata_used": {
        "description": "What vector databases are and when to use them."
      }
    },
    {
      "platform": "tiktok",
      "status": "published",
      "timestamp": "2026-01-15T10:30:00+00:00",
      "metadata_used": {
        "description": "What vector databases are and when to use them."
      }
    }
  ]
}
```

### Step 8: Self-Evaluate

Score (1-5):

| Criterion | Question |
|-----------|----------|
| **SEO quality** | Would this title and description rank well for the topic? |
| **Description completeness** | Does the description include chapters, CTA, and keywords? |
| **Thumbnail concept** | Would this thumbnail stand out in a feed? |
| **Export package** | Is everything a creator needs in the export directory? |
| **Platform fit** | Is metadata tailored to the target platform? |
| **Auto-publish success** | Did all configured platforms accept the upload? |

If any dimension scores below 3, revise.

### Step 9: Submit

Validate the publish_log against the schema and persist via checkpoint.

## Common Pitfalls

- **Generic titles**: "Video About X" loses to "X Explained in 60 Seconds" every time. Be specific and compelling.
- **No chapters**: YouTube rewards videos with chapters. Always include them.
- **Description keyword stuffing**: Write for humans first, search engines second. Natural language with keywords woven in.
- **Forgetting the CTA**: Every description should end with a call to action.
- **Wrong platform format**: YouTube descriptions differ from TikTok captions. Tailor to the target platform.
- **Missing platform credentials**: Ensure all required tokens/cookies are configured in `.env`.
- **Temporary hosting issues**: Instagram requires a public video URL. Use Cloudflare R2 or similar for temporary hosting.
- **Sandbox restrictions**: Instagram publishing may be restricted until the app is approved for production use.

---

## Gate Reminder (Binding)

This stage gates on human approval (`human_approval_default: true`). After review passes:
checkpoint with `status="awaiting_human"`, present the summary (the Backlot board renders
the artifact), and **END YOUR TURN**. Do not start the next stage in the same response.
Approval is per-gate — an earlier "go ahead" does not cover this gate.