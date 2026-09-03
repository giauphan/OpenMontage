#!/bin/bash
# Direct Docker run command for CLAUDE Agent Validation Feature
# Usage: ./docker-validation-run.sh [project_id]

set -euo pipefail

PROJECT_ID="${1:-$(date +%Y%m%d)}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Running CLAUDE Agent Validation in Docker..."
echo "Project ID: $PROJECT_ID"

# Capture exit code from docker command, not from echo
docker-compose run --rm worker bash -c \
  "cd /app && \
   python3 scripts/claude_agent_validation.py projects/$PROJECT_ID --strict --retry 2"

# Capture the actual exit code from docker command
exit_code=$?

echo "Validation completed. Exit code: $exit_code"

# Check exit code and provide clear status
if [ $exit_code -eq 0 ]; then
    echo "🟢 STRICT QUALITY VALIDATION PASSED"
    exit 0
else
    echo "🔴 STRICT QUALITY VALIDATION FAILED"
    exit 1
fi