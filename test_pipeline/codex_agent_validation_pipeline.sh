#!/usr/bin/env bash
# Codex Agent Validation Test Pipeline
# This script creates a test environment, runs validation tests, and verifies results

set -euo pipefail

# Configuration
TEST_DIR="test_project_$(date +%Y%m%d_%H%M%S)"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$ROOT_DIR/projects/$TEST_DIR"

# Create test project
create_test_project() {
    echo "Creating test project: $TEST_DIR"
    mkdir -p "$PROJECT_DIR"
    mkdir -p "$PROJECT_DIR/renders"
    mkdir -p "$PROJECT_DIR/artifacts"
    mkdir -p "$PROJECT_DIR/hyperframes"
    mkdir -p "$PROJECT_DIR/hyperframes_reels"

    # Create test video files
    echo "Creating test video files..."
    for render in full_vi_9x16 reels_vi_9x16; do
        ffmpeg -y -f lavfi -i testsrc=size=1080x1920:rate=30:duration=15 -f lavfi -i sine=frequency=1000:duration=15 -c:v libx264 -pix_fmt yuv420p -c:a aac -shortest "$PROJECT_DIR/renders/final_${render}.mp4" >/dev/null 2>&1
    done

    # Create test metadata
    cat > "$PROJECT_DIR/publish_metadata.json" <<EOL
{
    "title": "Test Video #tintuc #congnghe #ai",
    "description": "This is a test video for validation #tintuc #congnghe #ai",
    "yt_shorts": {"title": "Test Video #Shorts #tintuc #congnghe #ai"},
    "tiktok": {"title": "Test Video"},
    "fb_video": {"title": "Test Video"},
    "ig_reels": {"title": "Test Video"}
}
EOL

    # Create test artifacts
    cat > "$PROJECT_DIR/artifacts/script_vi.json" <<EOL
{
    "title": "Test Video",
    "sections": [
        {"id": "hook", "text_vi": "Khám phá công nghệ AI mới nhất hôm nay."},
        {"id": "body", "text_vi": "Hệ thống AI tự động hóa hoàn toàn quy trình sản xuất."}
    ]
}
EOL

    # Create test compositions
    for dir in hyperframes hyperframes_reels; do
        cat > "$PROJECT_DIR/$dir/index.html" <<EOL
<!DOCTYPE html>
<html>
<head><title>Test Composition</title></head>
<body>
    <div class="scene" data-scene-id="scene1"><h1>Tin tức AI</h1></div>
    <div class="scene" data-scene-id="scene2"><p>Đột phá công nghệ mới</p></div>
</body>
</html>
EOL
    done
}

# Run validation tests
execute_validation_tests() {
    echo "Running Codex Agent validation..."
    python3 "$ROOT_DIR/scripts/codex_agent_validation.py" "$PROJECT_DIR" --strict
}

# Verify test results
verify_test_results() {
    echo "Verifying validation results..."
    if [ -f "$PROJECT_DIR/validation_status.json" ]; then
        echo "✅ Validation status file exists"
        jq -r '.[-1] | "Status: \(.status), Passed: \(.passed)/\(.total_checks)"' "$PROJECT_DIR/validation_status.json"
    else
        echo "❌ Validation status file missing"
        return 1
    fi
    return 0
}

# Clean up test project
cleanup_test_project() {
    echo "Cleaning up test project: $TEST_DIR"
    rm -rf "$PROJECT_DIR"
}

main() {
    echo "===== CODEX AGENT VALIDATION TEST PIPELINE ====="
    trap cleanup_test_project EXIT
    create_test_project
    execute_validation_tests
    verify_test_results
    echo "===== TEST PIPELINE COMPLETE ====="
}

main
