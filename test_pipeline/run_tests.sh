#!/bin/bash
# CLAUDE Agent Validation Test Runner
# This script provides various ways to test the CLAUDE validation implementation

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "🧪 CLAUDE Agent Validation Test Runner"
echo "======================================"
echo ""
echo "Available Test Options:"
echo "1. Run Python Unit Tests (no Docker/dependencies needed)"
echo "2. Run Docker Integration Tests (requires Docker)"
echo "3. Run All Tests"
echo "4. Quick Syntax Check"
echo "5. Docker Validation Script Test"
echo ""

run_python_tests() {
    echo "\n🔧 Running Python Unit Tests..."
    echo "================================"
    
    python3 "$ROOT_DIR/test_pipeline/test_claude_validation.py"
    return $?
}

run_docker_integration_tests() {
    echo "\n🐳 Running Docker Integration Tests..."
    echo "==================================="
    
    # Check if Docker is running
    if ! docker info >/dev/null 2>&1; then
        echo "❌ Docker is not running. Please start Docker and try again."
        return 1
    fi
    
    # Check if we can build the containers
    echo "Checking Docker containers..."
    if docker-compose -f "$ROOT_DIR/docker-compose.yml" ps >/dev/null 2>&1; then
        echo "✅ Docker containers available"
    else
        echo "⚠️  Docker containers not running. Attempting to start..."
        cd "$ROOT_DIR"
        if ! docker-compose up -d; then
            echo "❌ Failed to start Docker containers"
            return 1
        fi
        sleep 10  # Give containers time to start
    fi
    
    # Execute the Docker test pipeline
    echo "Executing Docker test pipeline..."
    bash "$ROOT_DIR/test_pipeline/claude_agent_validation_pipeline.sh"
    return $?
}

run_quick_syntax_check() {
    echo "\n✅ Running Quick Syntax Check..."
    echo "=============================="
    
    error_count=0
    
    # Check Python files
    files=(
        "scripts/claude_agent_validation.py"
        "scripts/validation_status.py" 
        "test_pipeline/test_claude_validation.py"
        "test_pipeline/claude_agent_validation_pipeline.sh"
    )
    
    for file in "${files[@]}"; do
        if python3 -m py_compile "$ROOT_DIR/$file" 2>/dev/null; then
            echo "✅ $file syntax OK"
        else
            echo "❌ $file syntax ERROR"
            error_count=$((error_count + 1))
        fi
    done
    
    # Check shell scripts
    bash_files=(
        "test_pipeline/claude_agent_validation_pipeline.sh"
        "docker-validation-run.sh"
    )
    
    for file in "${bash_files[@]}"; do
        if bash -n "$ROOT_DIR/$file" 2>/dev/null; then
            echo "✅ $file syntax OK"
        else
            echo "❌ $file syntax ERROR"
            error_count=$((error_count + 1))
        fi
    done
    
    if [ $error_count -eq 0 ]; then
        echo "\n🎉 All syntax checks PASSED"
        return 0
    else
        echo "\n❌ $error_count syntax errors found"
        return 1
    fi
}

run_docker_validation_test() {
    echo "\n🐳 Running Direct Docker Validation Test..."
    echo "=========================================="
    
    # Test if we can run validation directly
    echo "Testing CLAUDE validation script directly..."
    
    # Create a simple test directory
    TEST_DIR=$(mktemp -d)
    mkdir -p "$TEST_DIR/renders"
    
    # Create minimal test video (1 second of test pattern)
    ffmpeg -f lavfi -i testsrc=size=1080x1920:rate=30:duration=31 -c:v libx264 -pix_fmt yuv420p -crf 23 "$TEST_DIR/renders/final_full_vi_9x16.mp4" 2>/dev/null || {
        echo "⚠️  ffmpeg not available, using placeholder files"
        touch "$TEST_DIR/renders/final_full_vi_9x16.mp4"
        touch "$TEST_DIR/renders/final_reels_vi_9x16.mp4"
    }
    
    # Create metadata
    cat > "$TEST_DIR/publish_metadata.json" <<EOL
{
    "title": "Test Video #tintuc #congnghe #ai",
    "description": "Test description"
}
EOL
    
    # Run validation test
    echo "Running validation on test directory..."
    python3 "$ROOT_DIR/scripts/claude_agent_validation.py" "$TEST_DIR" --retry 1
    exit_code=$?
    
    # Cleanup
    rm -rf "$TEST_DIR"
    
    return $exit_code
}

# Main execution
echo ""
read -p "Choose test option (1-5): " choice

case $choice in
    1)
        run_python_tests
        ;;
    2)
        run_docker_integration_tests
        ;;
    3)
        echo "Running All Tests..."
        run_quick_syntax_check
        if [ $? -eq 0 ]; then
            run_python_tests
            if [ $? -eq 0 ]; then
                run_docker_integration_tests
            fi
        fi
        ;;
    4)
        run_quick_syntax_check
        ;;
    5)
        run_docker_validation_test
        ;;
    *)
        echo "Invalid choice. Please select 1-5."
        exit 1
        ;;
esac
exit $?