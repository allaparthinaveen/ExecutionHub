#!/usr/bin/env bash
# =============================================================
# Samurai Engine — EC2 t2.micro Bootstrap Script
# Run once on a fresh Ubuntu 22.04 instance:
#   chmod +x deploy/setup.sh && sudo ./deploy/setup.sh
# =============================================================
set -euo pipefail

REPO_URL="https://github.com/allaparthinaveen/ExecutionHub.git"
APP_DIR="/home/ubuntu/ExecutionHub/trading_engine"
SERVICE_NAME="samurai"
PYTHON_MIN="3.12"

echo ""
echo "=================================================="
echo "  Samurai Engine — EC2 Deployment Setup"
echo "=================================================="
echo ""

# ── 1. System packages ───────────────────────────────
echo "[1/7] Installing system packages..."
apt-get update -qq
apt-get install -y -qq \
    python3.12 \
    python3.12-venv \
    python3-pip \
    git \
    curl \
    htop \
    unzip

# ── 2. Clone / update repo ───────────────────────────
echo "[2/7] Cloning repository..."
if [ -d "/home/ubuntu/ExecutionHub" ]; then
    echo "  Repo already exists — pulling latest..."
    cd /home/ubuntu/ExecutionHub
    git pull origin signalengine
else
    cd /home/ubuntu
    git clone -b signalengine "$REPO_URL"
fi

# ── 3. Python venv + dependencies ───────────────────
echo "[3/7] Setting up Python virtual environment..."
cd "$APP_DIR"
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q

# Install the package itself (editable)
pip install -e . -q

echo "  Dependencies installed OK."

# ── 4. .env file ─────────────────────────────────────
echo "[4/7] Checking .env file..."
if [ ! -f "$APP_DIR/.env" ]; then
    cp "$APP_DIR/.env.example" "$APP_DIR/.env"
    echo ""
    echo "  ⚠️  ACTION REQUIRED:"
    echo "  Edit your secrets file before starting the engine:"
    echo "    nano $APP_DIR/.env"
    echo ""
fi

# Fix ownership
chown -R ubuntu:ubuntu /home/ubuntu/ExecutionHub

# ── 5. Logs directory ────────────────────────────────
echo "[5/7] Creating logs directory..."
mkdir -p "$APP_DIR/logs"
chown ubuntu:ubuntu "$APP_DIR/logs"

# ── 6. Install systemd service ───────────────────────
echo "[6/7] Installing systemd service..."
cp "$APP_DIR/deploy/samurai.service" /etc/systemd/system/samurai.service
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"

# ── 7. Done ──────────────────────────────────────────
echo ""
echo "=================================================="
echo "  ✅ Setup complete!"
echo "=================================================="
echo ""
echo "  Next steps:"
echo "  1. Fill in your API keys:"
echo "       nano $APP_DIR/.env"
echo ""
echo "  2. Start the engine:"
echo "       sudo systemctl start samurai"
echo ""
echo "  3. Check it's running:"
echo "       sudo systemctl status samurai"
echo ""
echo "  4. Watch live logs:"
echo "       sudo journalctl -u samurai -f"
echo ""
echo "  5. Stop the engine:"
echo "       sudo systemctl stop samurai"
echo ""
