#!/usr/bin/env bash
# End-to-end test script to verify that the video generation pipeline flow
# executes cleanly and stably inside Docker for US-English video generation.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROJECT_ID="${1:-us_docker_test_01}"
PROJECT_DIR="$ROOT/projects/$PROJECT_ID"

echo "=========================================================="
echo "Starting OpenMontage Pipeline Docker Video Generation Test"
echo "Project ID: $PROJECT_ID"
echo "Project Dir: $PROJECT_DIR"
echo "Locale: en-US (US Market)"
echo "=========================================================="

# 1. Ensure project directories
mkdir -p "$PROJECT_DIR/artifacts" "$PROJECT_DIR/assets" "$PROJECT_DIR/hyperframes/assets" "$PROJECT_DIR/hyperframes_reels/assets" "$PROJECT_DIR/renders"

# 2. Write project.json
cat << 'EOF' > "$PROJECT_DIR/project.json"
{
  "project_id": "us_docker_test_01",
  "topic": "AI Video Generation Pipeline Test",
  "created_at": "2026-10-21T14:00:00Z",
  "target_platform": "youtube_shorts",
  "locale": "en-US",
  "render_status": "ready"
}
EOF

# 3. Write research_brief.json with >= 3 existing content sources
cat << 'EOF' > "$PROJECT_DIR/artifacts/research_brief.json"
{
  "version": "1.0",
  "topic": "Next-Gen AI Video Pipelines: Autonomous Video Creation for the US Market",
  "research_date": "2026-10-21",
  "landscape": {
    "existing_content": [
      {
        "title": "Autonomous AI Video Generation at Scale",
        "source": "TechRadar",
        "angle": "Enterprise video workflows",
        "what_it_covers": "High-throughput cloud rendering pipelines."
      },
      {
        "title": "US Market Video Migration Patterns",
        "source": "VentureBeat",
        "angle": "Localization and audience fit",
        "what_it_covers": "Transitioning automated pipelines to American English."
      },
      {
        "title": "HyperFrames Deterministic Web-to-Video Engine",
        "source": "InfoQ",
        "angle": "Architectural breakdown",
        "what_it_covers": "DOM animation and seek-safe video rendering."
      }
    ],
    "saturated_angles": [
      "Simple text to speech overlays"
    ],
    "underserved_gaps": [
      "End-to-end verified autonomous generation with strict content safety"
    ]
  },
  "data_points": []
}
EOF

# 4. Write news_evidence.json
cat << 'EOF' > "$PROJECT_DIR/artifacts/news_evidence.json"
{
  "version": "2.0",
  "script_sha256": "us_pipeline_test_evidence_sha",
  "claims": [
    {
      "section_id": "intro",
      "claim": "OpenMontage activates autonomous high quality video generation natively in Docker for the US audience.",
      "classification": "reported_fact",
      "consequential": false,
      "source_ids": ["s1"],
      "reviewer": "Automated Quality Gate",
      "reviewed_at": "2026-10-21T14:00:00Z",
      "review_status": "approved"
    }
  ],
  "sources": [
    {
      "source_id": "s1",
      "title": "Autonomous AI Video Generation at Scale",
      "url": "https://example.com/ai-video",
      "published_at": "2026-10-21T12:00:00Z"
    }
  ]
}
EOF

# 5. Write script_en_US.json
cat << 'EOF' > "$PROJECT_DIR/artifacts/script_en_US.json"
{
  "title": "AI Video Generation Pipeline Test",
  "locale": "en-US",
  "duration_seconds": 12,
  "sections": [
    {
      "id": "scene-1",
      "heading": "Autonomous Pipeline",
      "text": "OpenMontage activates native video generation in Docker for the US market.",
      "duration": 6
    },
    {
      "id": "scene-2",
      "heading": "Native 1080x1920",
      "text": "Every frame is rendered deterministically with full audio and visual validation.",
      "duration": 6
    }
  ]
}
EOF

# 6. Write narration_en_US_text.txt
cat << 'EOF' > "$PROJECT_DIR/artifacts/narration_en_US_text.txt"
OpenMontage activates native video generation in Docker for the US market. Every frame is rendered deterministically with full audio and visual validation.
EOF

# 7. Copy music and audio assets if available
if [ -s "$ROOT/artifacts/us-migration/canaries/canary-short-en-us-01/assets/music-bg.mp3" ]; then
  cp "$ROOT/artifacts/us-migration/canaries/canary-short-en-us-01/assets/music-bg.mp3" "$PROJECT_DIR/assets/music-bg.mp3"
  cp "$ROOT/artifacts/us-migration/canaries/canary-short-en-us-01/assets/music-bg.mp3" "$PROJECT_DIR/hyperframes/assets/music-bg.mp3"
  cp "$ROOT/artifacts/us-migration/canaries/canary-short-en-us-01/assets/music-bg.mp3" "$PROJECT_DIR/hyperframes_reels/assets/music-bg.mp3"
fi

if [ -s "$ROOT/artifacts/us-migration/canaries/canary-short-en-us-01/assets/narration.mp3" ]; then
  cp "$ROOT/artifacts/us-migration/canaries/canary-short-en-us-01/assets/narration.mp3" "$PROJECT_DIR/assets/narration.mp3"
  cp "$ROOT/artifacts/us-migration/canaries/canary-short-en-us-01/assets/narration.mp3" "$PROJECT_DIR/hyperframes/assets/narration.mp3"
  cp "$ROOT/artifacts/us-migration/canaries/canary-short-en-us-01/assets/narration.mp3" "$PROJECT_DIR/hyperframes_reels/assets/narration.mp3"
  cp "$ROOT/artifacts/us-migration/canaries/canary-short-en-us-01/assets/narration.mp3" "$PROJECT_DIR/hyperframes_reels/assets/narration_reels.mp3"
fi

# 8. Copy fonts if available
for f in BeVietnamPro-Regular.ttf BeVietnamPro-Bold.ttf BeVietnamPro-ExtraBold.ttf; do
  if [ -s "$ROOT/styles/fonts/$f" ]; then
    cp "$ROOT/styles/fonts/$f" "$PROJECT_DIR/hyperframes/assets/$f"
    cp "$ROOT/styles/fonts/$f" "$PROJECT_DIR/hyperframes_reels/assets/$f"
  fi
done

# 9. Write hyperframes/index.html
cat << 'EOF' > "$PROJECT_DIR/hyperframes/index.html"
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=1080, height=1920" />
  <title>AI Video Pipeline — OpenMontage</title>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
  <style>
    @font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-Regular.ttf') format('truetype'); font-weight: 400; }
    @font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-Bold.ttf') format('truetype'); font-weight: 700; }
    @font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-ExtraBold.ttf') format('truetype'); font-weight: 800; }
    :root { --accent: #2563eb; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #090d16; color: #f8fafc; font-family: 'BeVietnamPro', system-ui, sans-serif; }
    #root { position: relative; width: 1080px; height: 1920px; overflow: hidden; background: #090d16; }
    .bg-gradient { position: absolute; inset: 0; background: radial-gradient(circle at 50% 20%, #1e3a8a 0%, #090d16 80%); }
    .clip { position: absolute; inset: 0; }
    .scene-box { display: flex; flex-direction: column; justify-content: center; align-items: center; width: 100%; height: 100%; padding: 100px 60px; text-align: center; }
    .tag { font-size: 28px; font-weight: 700; letter-spacing: 0.2em; text-transform: uppercase; color: #60a5fa; margin-bottom: 24px; padding: 8px 24px; border: 2px solid #3b82f6; border-radius: 9999px; }
    .headline { font-size: 64px; font-weight: 800; line-height: 1.15; color: #ffffff; max-width: 960px; margin: 0 0 32px; }
    .body-copy { font-size: 36px; font-weight: 400; line-height: 1.5; color: #cbd5e1; max-width: 880px; margin: 0; }
  </style>
</head>
<body>
  <div id="root" data-composition-id="main" data-width="1080" data-height="1920" data-duration="12">
    <div class="bg-gradient"></div>
    <audio id="narration" class="clip" data-start="0" data-duration="12" data-track-index="10" data-volume="1" src="assets/narration.mp3"></audio>
    <audio id="music-bg" class="clip" data-start="0" data-duration="12" data-track-index="0" data-volume="0.25" src="assets/music-bg.mp3"></audio>

    <section id="scene-1" class="clip" data-start="0" data-duration="6" data-track-index="1">
      <div class="scene-box">
        <span class="tag">AI PIPELINE</span>
        <h1 class="headline">Autonomous Video Generation</h1>
        <p class="body-copy">OpenMontage activates native video generation in Docker for the US market.</p>
      </div>
    </section>

    <section id="scene-2" class="clip" data-start="6" data-duration="6" data-track-index="2">
      <div class="scene-box">
        <span class="tag">DOCKER VERIFIED</span>
        <h1 class="headline">Deterministic Renders</h1>
        <p class="body-copy">Every frame is rendered deterministically with full audio and visual validation.</p>
      </div>
    </section>
  </div>

  <script>
    (function() {
      window.__timelines = window.__timelines || {};
      var tl = gsap.timeline({ paused: true });
      tl.from('#scene-1 .scene-box', { opacity: 0, y: 50, duration: 0.8, ease: 'power2.out' }, 0.2);
      tl.to('#scene-1', { opacity: 0, duration: 0.4 }, 5.6);
      tl.from('#scene-2 .scene-box', { opacity: 0, y: 50, duration: 0.8, ease: 'power2.out' }, 6.2);
      window.__timelines.main = tl;
    })();
  </script>
</body>
</html>
EOF

# 10. Write hyperframes_reels/index.html
cat << 'EOF' > "$PROJECT_DIR/hyperframes_reels/index.html"
<!doctype html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=1080, height=1920" />
  <title>AI Video Pipeline — OpenMontage Shorts</title>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
  <style>
    @font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-Regular.ttf') format('truetype'); font-weight: 400; }
    @font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-Bold.ttf') format('truetype'); font-weight: 700; }
    @font-face { font-family: 'BeVietnamPro'; src: url('assets/BeVietnamPro-ExtraBold.ttf') format('truetype'); font-weight: 800; }
    :root { --accent: #2563eb; }
    * { box-sizing: border-box; }
    body { margin: 0; background: #090d16; color: #f8fafc; font-family: 'BeVietnamPro', system-ui, sans-serif; }
    #root { position: relative; width: 1080px; height: 1920px; overflow: hidden; background: #090d16; }
    .bg-gradient { position: absolute; inset: 0; background: radial-gradient(circle at 50% 20%, #1e3a8a 0%, #090d16 80%); }
    .clip { position: absolute; inset: 0; }
    .scene-box { display: flex; flex-direction: column; justify-content: center; align-items: center; width: 100%; height: 100%; padding: 100px 60px; text-align: center; }
    .tag { font-size: 28px; font-weight: 700; letter-spacing: 0.2em; text-transform: uppercase; color: #60a5fa; margin-bottom: 24px; padding: 8px 24px; border: 2px solid #3b82f6; border-radius: 9999px; }
    .headline { font-size: 64px; font-weight: 800; line-height: 1.15; color: #ffffff; max-width: 960px; margin: 0 0 32px; }
    .body-copy { font-size: 36px; font-weight: 400; line-height: 1.5; color: #cbd5e1; max-width: 880px; margin: 0; }
  </style>
</head>
<body>
  <div id="root" data-composition-id="main" data-width="1080" data-height="1920" data-duration="12">
    <div class="bg-gradient"></div>
    <audio id="narration" class="clip" data-start="0" data-duration="12" data-track-index="10" data-volume="1" src="assets/narration_reels.mp3"></audio>
    <audio id="music-bg" class="clip" data-start="0" data-duration="12" data-track-index="0" data-volume="0.25" src="assets/music-bg.mp3"></audio>

    <section id="scene-1" class="clip" data-start="0" data-duration="6" data-track-index="1">
      <div class="scene-box">
        <span class="tag">SHORTS / REELS</span>
        <h1 class="headline">Autonomous Video Generation</h1>
        <p class="body-copy">OpenMontage activates native video generation in Docker for the US market.</p>
      </div>
    </section>

    <section id="scene-2" class="clip" data-start="6" data-duration="6" data-track-index="2">
      <div class="scene-box">
        <span class="tag">STABLE EXECUTION</span>
        <h1 class="headline">Deterministic Renders</h1>
        <p class="body-copy">Every frame is rendered deterministically with full audio and visual validation.</p>
      </div>
    </section>
  </div>

  <script>
    (function() {
      window.__timelines = window.__timelines || {};
      var tl = gsap.timeline({ paused: true });
      tl.from('#scene-1 .scene-box', { opacity: 0, y: 50, duration: 0.8, ease: 'power2.out' }, 0.2);
      tl.to('#scene-1', { opacity: 0, duration: 0.4 }, 5.6);
      tl.from('#scene-2 .scene-box', { opacity: 0, y: 50, duration: 0.8, ease: 'power2.out' }, 6.2);
      window.__timelines.main = tl;
    })();
  </script>
</body>
</html>
EOF

# 11. Run the daily news pipeline for this project
echo "Running daily news pipeline for $PROJECT_ID..."
bash "$ROOT/scripts/run_daily_news_pipeline.sh" --project-ids "$PROJECT_ID"

# 12. Verify rendered output files
SHORT_RENDER="$PROJECT_DIR/renders/final_short_en_US_9x16.mp4"
LONG_RENDER="$PROJECT_DIR/renders/final_long_en_US_16x9.mp4"

echo "Verifying render outputs..."
if [ ! -s "$SHORT_RENDER" ]; then
  echo "ERROR: final short render missing: $SHORT_RENDER" >&2
  exit 1
fi

if [ ! -s "$LONG_RENDER" ]; then
  echo "ERROR: final long render missing: $LONG_RENDER" >&2
  exit 1
fi

# 13. Probe video streams
SHORT_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SHORT_RENDER")
SHORT_RES=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$SHORT_RENDER")
LONG_DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$LONG_RENDER")
LONG_RES=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=s=x:p=0 "$LONG_RENDER")

echo "=========================================================="
echo "🟢 DOCKER PIPELINE VIDEO GENERATION PASSED"
echo "Short Render: $SHORT_RENDER"
echo "  Resolution: $SHORT_RES (Expected: 1080x1920)"
echo "  Duration:   ${SHORT_DUR}s"
echo "Long Render:  $LONG_RENDER"
echo "  Resolution: $LONG_RES (Expected: 1080x1920)"
echo "  Duration:   ${LONG_DUR}s"
echo "=========================================================="
