#!/usr/bin/env bash
# Docker Pipeline Stability Checker
# Ensures all Docker services are healthy and Vietnamese subtitle pipeline works correctly

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo "[$(date -u +%FT%TZ)] $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Check if Docker and Docker Compose are available
check_docker_availability() {
    log "Checking Docker availability..."
    
    if ! command -v docker >/dev/null 2>&1; then
        error "Docker is not installed or not in PATH"
        return 1
    fi
    
    if ! docker info >/dev/null 2>&1; then
        error "Docker daemon is not running"
        return 1
    fi
    
    if ! command -v docker-compose >/dev/null 2>&1 && ! docker compose version >/dev/null 2>&1; then
        error "Docker Compose is not available"
        return 1
    fi
    
    success "Docker and Docker Compose are available"
    return 0
}

# Build containers if needed
ensure_containers_built() {
    log "Ensuring Docker containers are built..."
    
    # Check if images exist
    if ! docker images | grep -q openmontage; then
        warning "OpenMontage image not found, building..."
        docker compose build --no-cache || {
            error "Failed to build Docker containers"
            return 1
        }
    fi
    
    success "Docker containers are ready"
    return 0
}

# Test container startup
test_container_startup() {
    log "Testing container startup..."
    
    # Test worker container
    if ! timeout 60 docker compose run --rm worker echo "Container test successful"; then
        error "Worker container failed to start"
        return 1
    fi
    
    success "Container startup test passed"
    return 0
}

# Test critical dependencies in container
test_dependencies() {
    log "Testing dependencies in container..."
    
    local failed=0
    
    # Test each dependency
    local deps=(
        "python3 --version"
        "node --version"
        "npm --version"
        "ffmpeg -version"
        "ffprobe -version"
        "edge-tts --help"
    )
    
    for dep in "${deps[@]}"; do
        if ! timeout 30 docker compose run --rm worker $dep >/dev/null 2>&1; then
            error "Dependency check failed: $dep"
            ((failed++))
        else
            success "Dependency OK: ${dep%% *}"
        fi
    done
    
    # Test HyperFrames CLI
    if ! timeout 30 docker compose run --rm worker hyperframes --version >/dev/null 2>&1; then
        warning "HyperFrames CLI not available (this is OK for basic functionality)"
    else
        success "HyperFrames CLI available"
    fi
    
    if [ $failed -gt 0 ]; then
        error "$failed critical dependencies are missing"
        return 1
    fi
    
    success "All critical dependencies are available"
    return 0
}

# Test Vietnamese subtitle generation
test_vietnamese_subtitles() {
    log "Testing Vietnamese subtitle generation..."
    
    local test_text="Xin chào đây là bản tin kiểm tra phụ đề tiếng Việt"
    local temp_dir="/tmp/vn_subtitle_test_$(date +%s)"
    
    # Create test environment in container
    cat > /tmp/test_subtitle_generation.sh << EOF
#!/bin/bash
set -euo pipefail

mkdir -p "$temp_dir"
echo "$test_text" > "$temp_dir/test_narration.txt"

# Create a minimal test audio file (silence)
ffmpeg -f lavfi -i anullsrc=r=44100:cl=mono -t 5 -y "$temp_dir/test_audio.wav" >/dev/null 2>&1

# Test subtitle generation
python3 /app/scripts/generate_subtitles_from_text.py \\
    --narration-text "$temp_dir/test_narration.txt" \\
    --audio-path "$temp_dir/test_audio.wav" \\
    --output-srt "$temp_dir/test_subtitles.srt" \\
    --output-json "$temp_dir/test_timestamps.json" \\
    --max-words-per-cue 3

# Verify files were created and contain expected content
if [ ! -s "$temp_dir/test_subtitles.srt" ]; then
    echo "ERROR: SRT file not created or empty"
    exit 1
fi

if [ ! -s "$temp_dir/test_timestamps.json" ]; then
    echo "ERROR: JSON timestamps file not created or empty"
    exit 1
fi

# Check SRT format
if ! grep -q "00:00:00" "$temp_dir/test_subtitles.srt"; then
    echo "ERROR: Invalid SRT format"
    exit 1
fi

# Check Vietnamese text in subtitles
if ! grep -q "Xin chào" "$temp_dir/test_subtitles.srt"; then
    echo "ERROR: Vietnamese text not found in subtitles"
    exit 1
fi

# Check JSON format
if ! python3 -c "import json; json.load(open('$temp_dir/test_timestamps.json'))"; then
    echo "ERROR: Invalid JSON format"
    exit 1
fi

echo "SUCCESS: Vietnamese subtitle generation test passed"
rm -rf "$temp_dir"
EOF

    chmod +x /tmp/test_subtitle_generation.sh
    
    if timeout 120 docker compose run --rm worker bash /tmp/test_subtitle_generation.sh; then
        success "Vietnamese subtitle generation test passed"
        rm -f /tmp/test_subtitle_generation.sh
        return 0
    else
        error "Vietnamese subtitle generation test failed"
        rm -f /tmp/test_subtitle_generation.sh
        return 1
    fi
}

# Test pipeline script syntax and basic execution
test_pipeline_scripts() {
    log "Testing pipeline script syntax..."
    
    # Test shell script syntax
    if ! bash -n scripts/run_daily_news_pipeline.sh; then
        error "Shell script syntax error in run_daily_news_pipeline.sh"
        return 1
    fi
    
    # Test Python script syntax
    if ! docker compose run --rm worker python3 -m py_compile /app/scripts/generate_subtitles_from_text.py; then
        error "Python script syntax error in generate_subtitles_from_text.py"
        return 1
    fi
    
    # Test Python script help
    if ! timeout 30 docker compose run --rm worker python3 /app/scripts/generate_subtitles_from_text.py --help >/dev/null; then
        error "Python script execution test failed"
        return 1
    fi
    
    success "Pipeline script syntax and execution tests passed"
    return 0
}

# Test volume mounts and permissions
test_volume_mounts() {
    log "Testing volume mounts and permissions..."
    
    # Test write permissions
    if ! docker compose run --rm worker touch /app/test_write_permission; then
        error "Cannot write to mounted volume"
        return 1
    fi
    
    # Clean up test file
    rm -f "$ROOT/test_write_permission"
    
    # Test node_modules volume
    if ! docker compose run --rm worker test -d /app/node_modules; then
        warning "node_modules volume not properly mounted"
    fi
    
    success "Volume mounts and permissions test passed"
    return 0
}

# Test network connectivity (if needed)
test_network_connectivity() {
    log "Testing network connectivity..."
    
    # Test basic internet connectivity
    if ! timeout 10 docker compose run --rm worker ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        warning "No internet connectivity (this may be expected in some environments)"
    else
        success "Network connectivity available"
    fi
    
    return 0
}

# Run comprehensive stability check
run_stability_check() {
    log "Starting Docker Pipeline Stability Check"
    echo "================================"
    
    local failed_tests=0
    local total_tests=0
    
    local tests=(
        "check_docker_availability"
        "ensure_containers_built"
        "test_container_startup"
        "test_dependencies"
        "test_vietnamese_subtitles"
        "test_pipeline_scripts"
        "test_volume_mounts"
        "test_network_connectivity"
    )
    
    for test in "${tests[@]}"; do
        ((total_tests++))
        echo
        if $test; then
            success "✓ $test"
        else
            error "✗ $test"
            ((failed_tests++))
        fi
    done
    
    echo
    echo "================================"
    log "Stability Check Results"
    
    if [ $failed_tests -eq 0 ]; then
        success "🎉 All $total_tests tests passed! Docker pipeline is stable."
        return 0
    else
        error "❌ $failed_tests out of $total_tests tests failed."
        
        if [ $failed_tests -le 2 ]; then
            warning "Pipeline may still be functional with minor issues."
            return 1
        else
            error "Pipeline has significant stability issues."
            return 2
        fi
    fi
}

# Recovery mode - attempt to fix common issues
run_recovery() {
    log "Starting Docker Pipeline Recovery"
    echo "================================"
    
    warning "Attempting to recover from stability issues..."
    
    # Stop all containers
    log "Stopping all containers..."
    docker compose down || true
    
    # Clean up Docker resources
    log "Cleaning up Docker resources..."
    docker system prune -f || true
    
    # Rebuild containers
    log "Rebuilding containers..."
    if docker compose build --no-cache; then
        success "Containers rebuilt successfully"
    else
        error "Failed to rebuild containers"
        return 1
    fi
    
    # Test basic functionality
    log "Testing basic functionality after recovery..."
    if test_container_startup && test_dependencies; then
        success "🎉 Recovery successful! Pipeline is now stable."
        return 0
    else
        error "❌ Recovery failed. Manual intervention required."
        return 1
    fi
}

# Main function
main() {
    case "${1:-check}" in
        "check")
            run_stability_check
            ;;
        "recover")
            run_recovery
            ;;
        "monitor")
            # Continuous monitoring mode
            log "Starting continuous monitoring (Ctrl+C to stop)"
            while true; do
                run_stability_check
                if [ $? -eq 0 ]; then
                    log "Monitoring: Pipeline stable, sleeping for 5 minutes..."
                    sleep 300
                else
                    warning "Monitoring: Stability issues detected, checking again in 1 minute..."
                    sleep 60
                fi
            done
            ;;
        *)
            echo "Usage: $0 [check|recover|monitor]"
            echo "  check   - Run stability check (default)"
            echo "  recover - Attempt recovery from issues"
            echo "  monitor - Continuous monitoring mode"
            exit 1
            ;;
    esac
}

# Handle Ctrl+C gracefully
trap 'echo; warning "Interrupted by user"; exit 130' INT

main "$@"