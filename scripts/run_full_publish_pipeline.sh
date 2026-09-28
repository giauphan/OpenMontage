#!/usr/bin/env bash
# Full publish pipeline: Generate, validate, and publish videos for today and next day
# with strict Codex agent strict validation
# Runs on sandbox-video server via SSH
set -euo pipefail

# SSH command to run on sandbox-video server
SSH_CMD="ssh -F /home/ubuntu/.ssh/ssh-sandbox-video -i /home/ubuntu/.ssh/tunnel_key sandbox-video"

# Parse arguments
STRICT_FLAG=""
DRY_RUN_FLAG=""
FORCE_FLAG=""
TODAY_ONLY_FLAG=""
NEXT_DAY_ONLY_FLAG=""
HELP_FLAG=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --strict)
      STRICT_FLAG="--strict"
      shift
      ;;
    --no-strict)
      shift
      ;;
    --dry-run)
      DRY_RUN_FLAG="--dry-run"
      shift
      ;;
    --force)
      FORCE_FLAG="--force"
      shift
      ;;
    --today-only)
      TODAY_ONLY_FLAG="--today-only"
      shift
      ;;
    --next-day-only)
      NEXT_DAY_ONLY_FLAG="--next-day-only"
      shift
      ;;
    --help|-h)
      HELP_FLAG="1"
      shift
      ;;
    *)
      shift
      ;;
  esac
done

# Print usage
usage() {
  cat <<EOF
Usage: $0 [OPTIONS]

Full publish pipeline: Generate, validate, and publish videos for today and next day
Runs on sandbox-video server via SSH

Options:
  --strict          Enable mandatory Codex agent strict validation (default)
  --no-strict       Disable strict validation
  --today-only      Only publish for today's date
  --next-day-only   Only publish for next day's date
  --dry-run         Validate and prepare but don't actually publish
  --force           Bypass validation failures (dangerous)
  --help, -h        Show this help message

Examples:
  $0                          # Full pipeline for today and tomorrow with strict validation
  $0 --today-only             # Only today's publish
  $0 --next-day-only          # Only tomorrow's publish
  $0 --strict --dry-run       # Validate without publishing
EOF
}

if [ -n "$HELP_FLAG" ]; then
  usage
  exit 0
fi

# Run full publish pipeline on sandbox-video server
$SSH_CMD "cd ~/OpenMontage && ./scripts/run_full_publish_pipeline.sh $STRICT_FLAG $DRY_RUN_FLAG $FORCE_FLAG $TODAY_ONLY_FLAG $NEXT_DAY_ONLY_FLAG"
