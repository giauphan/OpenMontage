#!/bin/bash
# Direct Docker run command for Codex Agent Validation Feature
# Usage: ./docker-validation-run.sh [project_id]

set -euo pipefail

PROJECT_ID="${1:-$(date +%Y%m%d)}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Running Codex Agent Validation in Docker..."
echo "Project ID: $PROJECT_ID"

set +e
docker-compose run --rm worker bash -c \
  "cd /app && \
   python3 scripts/codex_agent_validation.py projects/$PROJECT_ID --strict --retry 2"
exit_code=$?
set -e

echo "Validation completed. Exit code: $exit_code"

if [ $exit_code -eq 0 ]; then
    echo "🟢 STRICT QUALITY VALIDATION PASSED"
    exit 0
else
    echo "🔴 STRICT QUALITY VALIDATION FAILED"
    exit 1
fi
