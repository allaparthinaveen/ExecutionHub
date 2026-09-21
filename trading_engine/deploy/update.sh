#!/usr/bin/env bash
# =============================================================
# Samurai Engine — Update Script (run after git push)
# Usage on EC2:  sudo ./deploy/update.sh
# =============================================================
set -euo pipefail

APP_DIR="/home/ubuntu/ExecutionHub/trading_engine"

echo ""
echo "[1/4] Pulling latest code from signalengine branch..."
cd /home/ubuntu/ExecutionHub
git pull origin signalengine

echo "[2/4] Updating Python dependencies..."
cd "$APP_DIR"
source venv/bin/activate
pip install -r requirements.txt -q
pip install -e . -q

echo "[3/4] Restarting Samurai Engine service..."
systemctl restart samurai

echo "[4/4] Service status:"
systemctl status samurai --no-pager

echo ""
echo "✅ Update complete! Live logs: sudo journalctl -u samurai -f"
echo ""
