#!/usr/bin/env bash
# OpenMontage - Remote Server Code Synchronization & Activation Flow
# Synchronizes latest code from origin/main to sandbox-video and activates
# Docker containers, pipeline scripts, and crontab in openmontage_scheduler.
#
# Execution rules compliance:
# - All code authoring and tests remain local.
# - SSH server performs fast-forward synchronization and validation only.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SSH_CONFIG="/home/ubuntu/.ssh/ssh-sandbox-video"
SSH_KEY="/home/ubuntu/.ssh/tunnel_key"
REMOTE_HOST="sandbox-video"
REMOTE_CHECKOUT="/home/ubuntu/OpenMontage"

RESTART_CONTAINERS=0
CHECK_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart)
      RESTART_CONTAINERS=1
      shift
      ;;
    --check-only)
      CHECK_ONLY=1
      shift
      ;;
    --help|-h)
      cat <<EOF
Usage: $0 [OPTIONS]

Synchronize latest local/origin code to sandbox-video server via SSH,
verify Docker containers, and ensure the pipeline and cronjob are active.

Options:
  --restart      Restart worker and scheduler containers after pulling code
  --check-only   Check remote server and cron status without pulling code
  --help, -h     Show this help message
EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [[ ! -f "$SSH_CONFIG" ]]; then
  echo "ERROR: SSH config not found at $SSH_CONFIG" >&2
  exit 1
fi

SSH_CMD="ssh -F $SSH_CONFIG"
if [[ -f "$SSH_KEY" ]]; then
  SSH_CMD="$SSH_CMD -i $SSH_KEY"
fi

echo "================================================================="
echo "OpenMontage Server Pull & Activation Flow"
echo "Target Host:     $REMOTE_HOST"
echo "Remote Checkout: $REMOTE_CHECKOUT"
echo "Local HEAD:      $(git -C "$ROOT" rev-parse --short HEAD) ($(git -C "$ROOT" log -1 --pretty=format:'%s'))"
echo "================================================================="

# Step 1: Verify SSH connectivity
echo ""
echo "[Step 1/5] Testing SSH connectivity to $REMOTE_HOST..."
$SSH_CMD "$REMOTE_HOST" "echo '[SSH OK] Connected to \$(hostname) as \$(whoami)'"

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  echo ""
  echo "[Check-Only Mode] Skipping git pull."
else
  # Step 2: Synchronize code via git fast-forward
  echo ""
  echo "[Step 2/5] Synchronizing code on $REMOTE_HOST ($REMOTE_CHECKOUT)..."
  $SSH_CMD "$REMOTE_HOST" "
    set -euo pipefail
    cd '$REMOTE_CHECKOUT'
    echo 'Fetching latest origin commits...'
    git fetch origin
    CURRENT_BRANCH=\$(git rev-parse --abbrev-ref HEAD)
    if [ \"\$CURRENT_BRANCH\" != \"main\" ]; then
      echo \"Switching to main branch (was \$CURRENT_BRANCH)...\"
      git checkout main
    fi
    echo 'Applying fast-forward pull...'
    git pull --ff-only origin main
    echo \"Remote revision is now at: \$(git rev-parse --short HEAD) - \$(git log -1 --pretty=format:'%s')\"
  "
fi

# Step 3: Verify Docker containers
echo ""
echo "[Step 3/5] Inspecting and ensuring Docker containers are running..."
$SSH_CMD "$REMOTE_HOST" "
  set -euo pipefail
  cd '$REMOTE_CHECKOUT'
  docker compose ps
"

if [[ "$RESTART_CONTAINERS" -eq 1 ]]; then
  echo "Restarting openmontage_worker and openmontage_scheduler containers..."
  $SSH_CMD "$REMOTE_HOST" "
    set -euo pipefail
    cd '$REMOTE_CHECKOUT'
    docker compose restart scheduler worker
    sleep 3
  "
fi

# Step 4: Ensure crontab is activated in openmontage_scheduler
echo ""
echo "[Step 4/5] Activating and verifying crontab in openmontage_scheduler..."
$SSH_CMD "$REMOTE_HOST" "
  set -euo pipefail
  cd '$REMOTE_CHECKOUT'
  # Ensure deploy/openmontage.cron is installed in openmontage_scheduler
  docker exec openmontage_scheduler crontab /app/deploy/openmontage.cron
  echo '[Crontab Updated] crontab in openmontage_scheduler refreshed from /app/deploy/openmontage.cron'

  # Verify cron daemon is running
  if docker exec openmontage_scheduler pgrep cron >/dev/null 2>&1; then
    echo '[Cron Daemon OK] cron service is running in openmontage_scheduler (PID: '\$(docker exec openmontage_scheduler pgrep cron)')'
  else
    echo '[Cron Daemon Restarting] starting cron daemon in openmontage_scheduler...'
    docker exec openmontage_scheduler cron
    echo '[Cron Daemon Started] PID: '\$(docker exec openmontage_scheduler pgrep cron)
  fi

  echo ''
  echo 'Active Crontab in openmontage_scheduler:'
  docker exec openmontage_scheduler crontab -l | grep -v '^#' | grep -v '^$'
"

# Step 5: Validate pipeline scripts syntax inside container
echo ""
echo "[Step 5/5] Validating pipeline script integrity inside openmontage_worker..."
$SSH_CMD "$REMOTE_HOST" "
  set -euo pipefail
  echo 'Validating scripts syntax inside worker container:'
  docker exec openmontage_worker bash -n /app/scripts/run_strict_docker_publish.sh && echo '  - run_strict_docker_publish.sh: OK'
  docker exec openmontage_worker bash -n /app/scripts/run_daily_news_pipeline.sh && echo '  - run_daily_news_pipeline.sh: OK'
  docker exec openmontage_worker bash -n /app/scripts/retry_daily_pipeline.sh && echo '  - retry_daily_pipeline.sh: OK'
  docker exec openmontage_worker python3 -m py_compile /app/scripts/validate_display_language.py && echo '  - validate_display_language.py: OK'
"

echo ""
echo "================================================================="
echo "Activation Complete!"
echo "Pipeline and cronjob are active and verified on $REMOTE_HOST."
echo "================================================================="
