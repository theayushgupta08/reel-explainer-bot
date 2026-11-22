#!/usr/bin/env bash
# One-time server setup for Ubuntu 22.04/24.04 (Oracle Cloud Always Free).
# Usage: sudo bash deploy/setup.sh   (run from inside the cloned repo)
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
APP_DIR=/opt/reel-bot

apt-get update
apt-get install -y python3 python3-venv python3-pip ffmpeg git

id reelbot &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin reelbot

# Small VMs have 1 GB RAM; add swap so video handling can't OOM the box.
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

mkdir -p "$APP_DIR"
if [ "$REPO_DIR" != "$APP_DIR" ]; then
  cp "$REPO_DIR"/bot.py "$REPO_DIR"/requirements.txt "$APP_DIR"/
fi
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet -U pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

[ -f "$APP_DIR/.env" ] || { echo "WARNING: copy your .env to $APP_DIR/.env"; }
chown -R reelbot:reelbot "$APP_DIR"
chmod 600 "$APP_DIR"/.env "$APP_DIR"/cookies.txt 2>/dev/null || true

cp "$REPO_DIR/deploy/reel-bot.service" /etc/systemd/system/reel-bot.service
systemctl daemon-reload
systemctl enable reel-bot
systemctl restart reel-bot
systemctl --no-pager status reel-bot || true
echo "Done. Logs: journalctl -u reel-bot -f"
