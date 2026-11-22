#!/usr/bin/env bash
# One-time server setup for Ubuntu 22.04/24.04 (Oracle Cloud Always Free).
# The app lives in a git checkout at /opt/reel-bot so /update in Telegram can pull new code.
# Usage: sudo bash /opt/reel-bot/deploy/setup.sh
set -euo pipefail
APP_DIR=/opt/reel-bot

apt-get update
apt-get install -y python3 python3-venv python3-pip ffmpeg git

id reelbot &>/dev/null || useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin reelbot

# Small VMs have 1 GB RAM; add swap so video handling can't OOM the box.
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

[ -d "$APP_DIR/.git" ] || { echo "Clone the repo into $APP_DIR first (see README)"; exit 1; }
[ -d "$APP_DIR/.venv" ] || python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --quiet -U pip
"$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

[ -f "$APP_DIR/.env" ] || echo "WARNING: put your .env in $APP_DIR/.env"
chown -R reelbot:reelbot "$APP_DIR"
chmod 600 "$APP_DIR"/.env "$APP_DIR"/cookies.txt 2>/dev/null || true

cp "$APP_DIR/deploy/reel-bot.service" /etc/systemd/system/reel-bot.service
systemctl daemon-reload
systemctl enable reel-bot
systemctl restart reel-bot
systemctl --no-pager status reel-bot || true
echo "Done. Logs: journalctl -u reel-bot -f   (or /logs in Telegram)"
