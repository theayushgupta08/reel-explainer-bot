#!/usr/bin/env bash
# Pull the latest code and restart. Usage: sudo bash deploy/update.sh
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
git -C "$REPO_DIR" pull --ff-only
cp "$REPO_DIR"/bot.py "$REPO_DIR"/requirements.txt /opt/reel-bot/
/opt/reel-bot/.venv/bin/pip install --quiet -r /opt/reel-bot/requirements.txt
cp "$REPO_DIR/deploy/reel-bot.service" /etc/systemd/system/reel-bot.service
chown -R reelbot:reelbot /opt/reel-bot
systemctl daemon-reload && systemctl restart reel-bot
echo "Updated. Logs: journalctl -u reel-bot -f"
