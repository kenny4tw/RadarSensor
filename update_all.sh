#!/usr/bin/env bash
# Update script for Ubuntu dashboard machine + Raspberry Pi
# Stops both services, pulls latest git on both, restarts everything
#
# Usage: bash update_all.sh [RPI_IP] [RPI_USER]
# Example: bash update_all.sh 192.168.1.45 radarmaster1
#
# If RPI_IP is not provided, it tries to read it from sensors.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

print_step() { echo -e "\n${BLUE}[$1]${NC} $2"; }
print_ok()   { echo -e "${GREEN}✓${NC} $1"; }
print_warn() { echo -e "${YELLOW}⚠${NC} $1"; }
print_err()  { echo -e "${RED}✗${NC} $1"; }

# ── Resolve RPI connection details ────────────────────────────────────────────
RPI_IP="${1:-}"
RPI_USER="${2:-radarmaster1}"
RPI_REPO_DIR="~/RadarSensor"

if [[ -z "$RPI_IP" ]] && command -v python3 &>/dev/null && [[ -f sensors.json ]]; then
    RPI_IP=$(python3 -c "
import json, sys
data = json.load(open('sensors.json'))
sensors = data.get('sensors', [])
host = sensors[0].get('host', '') if sensors else ''
# Skip placeholder / localhost
if host and host not in ('localhost', '127.0.0.1', '::1') and 'XXX' not in host:
    print(host)
" 2>/dev/null || true)
fi

if [[ -z "$RPI_IP" ]]; then
    print_err "RPI IP not found. Provide it as argument: bash update_all.sh <RPI_IP>"
    exit 1
fi

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║  UPDATE: Ubuntu dashboard + Raspberry Pi         ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo "  RPI:  ${RPI_USER}@${RPI_IP}"
echo "  Local: $SCRIPT_DIR"
echo ""

# ── Step 1: Stop dashboard locally (if running as a service) ─────────────────
print_step "1/5" "Stopping local dashboard (if running as systemd service)..."
if systemctl is-active --quiet dashboard 2>/dev/null; then
    sudo systemctl stop dashboard
    print_ok "Dashboard service stopped"
else
    print_warn "Dashboard not running as a service (skip)"
fi

# ── Step 2: Stop radar-daemon on RPI ─────────────────────────────────────────
print_step "2/5" "Stopping radar-daemon on RPI ${RPI_IP}..."
if ssh -o ConnectTimeout=10 "${RPI_USER}@${RPI_IP}" "sudo systemctl stop radar-daemon 2>/dev/null && echo stopped || echo not_running"; then
    print_ok "radar-daemon stopped on RPI"
else
    print_warn "Could not connect to RPI — continuing with local update only"
    RPI_IP=""
fi

# ── Step 3: git pull on Ubuntu ────────────────────────────────────────────────
print_step "3/5" "Pulling latest code on Ubuntu..."
git pull
print_ok "Local git pull done"

# ── Step 4: git pull + restart on RPI ────────────────────────────────────────
if [[ -n "$RPI_IP" ]]; then
    print_step "4/5" "Pulling latest code on RPI and restarting daemon..."
    ssh -o ConnectTimeout=10 "${RPI_USER}@${RPI_IP}" bash <<EOF
set -e
cd $RPI_REPO_DIR
echo "  → git pull..."
git pull
echo "  → Starting radar-daemon..."
sudo systemctl start radar-daemon
echo "  → Status:"
sudo systemctl status radar-daemon --no-pager -l | head -20
EOF
    print_ok "RPI updated and daemon restarted"
else
    print_step "4/5" "Skipped RPI update (not reachable)"
fi

# ── Step 5: Restart local dashboard ──────────────────────────────────────────
print_step "5/5" "Restarting local dashboard (if it was a service)..."
if systemctl list-unit-files dashboard.service &>/dev/null; then
    sudo systemctl start dashboard
    print_ok "Dashboard service restarted"
else
    print_warn "Dashboard is not a systemd service — start it manually:"
    echo "  cd $SCRIPT_DIR && python dashboard.py"
fi

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Update complete!${NC}"
echo ""
echo "  Check RPI daemon:   ssh ${RPI_USER}@${RPI_IP} 'sudo journalctl -u radar-daemon -n 30 --no-pager'"
echo "  Check API:          curl http://${RPI_IP}:8080/status"
echo ""
