#!/usr/bin/bash
# CLAUDE Agent Validation Test Pipeline
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

    # Create test video files
    echo "Creating test video files..."
    for size in 30 60; do
        for render in full_vi_9x16 reels_vi_9x16; do
            ffmpeg -f lavfi -i testsrc=size=1080x1920:rate=30:duration=$size -c:v libx264 -pix_fmt yuv420p -crf 23 "$PROJECT_DIR/renders/final_${render}.mp4"
        done
    done

    # Create test metadata
    cat > "$PROJECT_DIR/publish_metadata.json" <<EOL
{
    "title": "Test Video #tintuc #congnghe #ai",
    "description": "This is a test video for validation",
    "yt_shorts": {"title": "Test Video #Shorts"},
    "tiktok": {"title": "Test Video"},
    "fb_video": {"title": "Test Video"},
    "ig_reels": {"title": "Test Video"}
}
EOL

    # Create test artifacts
    cat > "$PROJECT_DIR/artifacts/script_vi.json" <<EOL
{
    "title": "Test Video",
    "description": "This is a test video"
}
EOL

    # Create test composition
    mkdir -p "$PROJECT_DIR/hyperframes"
    cat > "$PROJECT_DIR/hyperframes/index.html" <<EOL
<!DOCTYPE html>
<html>
<head>
    <title>Test Composition</title>
</head>
<body>
    <h1>Test Video Composition</h1>
</body>
</html>
EOL
}

# Run validation tests
execute_validation_tests() {
    echo "Running CLAUDE Agent validation tests..."

    # Test 1: Technical Contract Validation
    echo "\n=== TEST 1: TECHNICAL CONTRACT VALIDATION ==="
    docker-compose exec worker python3 scripts/claude_agent_validation.py "$PROJECT_DIR" \
        --strict \
        --retry 1 \
        --ffprobe ffprobe \
        --ffmpeg ffmpeg
    VALIDATION_EXIT=$?
    
    if [ $VALIDATION_EXIT -eq 0 ]; then
        echo "✅ TECHNICAL CONTRACT TEST PASSED"
    else
        echo "❌ TECHNICAL CONTRACT TEST FAILED"
        return 1
    fi

    # Test 2: Content Quality Validation
    echo "\n=== TEST 2: CONTENT QUALITY VALIDATION ==="
    docker-compose exec worker python3 scripts/validate_render_quality.py "$PROJECT_DIR" \
        --ffprobe ffprobe \
        --ffmpeg ffmpeg \
        --strict
    VALIDATION_EXIT=$?
    
    if [ $VALIDATION_EXIT -eq 0 ]; then
        echo "✅ CONTENT QUALITY TEST PASSED"
    else
        echo "❌ CONTENT QUALITY TEST FAILED"
        return 1
    fi

    # Test 3: Metadata Validation
    echo "\n=== TEST 3: METADATA VALIDATION ==="
    docker-compose exec worker python3 scripts/validate_publish_metadata.py "$PROJECT_DIR/publish_metadata.json"
    VALIDATION_EXIT=$?
    
    if [ $VALIDATION_EXIT -eq 0 ]; then
        echo "✅ METADATA TEST PASSED"
    else
        echo "❌ METADATA TEST FAILED"
        return 1
    fi

    # Test 4: CLAUDE Agent Validation
    echo "\n=== TEST 4: CLAUDE AGENT VALIDATION ==="
    docker-compose exec worker python3 scripts/claude_agent_validation.py "$PROJECT_DIR" \
        --strict \
        --retry 1
    VALIDATION_EXIT=$?
    
    if [ $VALIDATION_EXIT -eq 0 ]; then
        echo "✅ CLAUDE AGENT TEST PASSED"
    else
        echo "❌ CLAUDE AGENT TEST FAILED"
        return 1
    fi

    return 0
}

# Verify test results
verify_test_results() {
    echo "\n=== VERIFYING TEST RESULTS ==="

    # Check validation status
    if [ -f "$PROJECT_DIR/validation_status.json" ]; then
        echo "✅ Validation status file exists"
        cat "$PROJECT_DIR/validation_status.json"
    else
        echo "❌ Validation status file missing"
        return 1
    fi

    # Check logs
    if [ -f "$ROOT_DIR/logs/validation_log.txt" ]; then
        echo "✅ Validation log exists"
        tail -n 10 "$ROOT_DIR/logs/validation_log.txt"
    else
        echo "❌ Validation log missing"
        return 1
    fi

    return 0
}

# Clean up test project
cleanup_test_project() {
    echo "\n=== CLEANING UP TEST PROJECT ==="
    rm -rf "$PROJECT_DIR"
    echo "Test project $TEST_DIR removed"
}

# Main execution
main() {
    echo "\n===== CLAUDE AGENT VALIDATION TEST PIPELINE ====="
    echo "Test Project: $TEST_DIR"
    echo "Project Directory: $PROJECT_DIR"

    # Step 1: Create test project
    create_test_project
    
    # Step 2: Execute validation tests
    if execute_validation_tests; then
        echo "\n✅ ALL VALIDATION TESTS PASSED"
    else
        echo "\n❌ ONE OR MORE VALIDATION TESTS FAILED"
        cleanup_test_project
        exit 1
    fi

    # Step 3: Verify results
    if verify_test_results; then
        echo "\n✅ TEST RESULTS VERIFICATION PASSED"
    else
        echo "\n❌ TEST RESULTS VERIFICATION FAILED"
        cleanup_test_project
        exit 1
    fi

    # Step 4: Clean up
    cleanup_test_project

    echo "\n===== TEST PIPELINE COMPLETE ====="
    echo "Test Project: $TEST_DIR"
    echo "All tests passed successfully!"
    exit 0
}

main