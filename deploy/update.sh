#!/usr/bin/env bash
# Manual alternative to /update in Telegram. Usage: sudo bash /opt/reel-bot/deploy/update.sh
set -euo pipefail
cd /opt/reel-bot
sudo -u reelbot git pull --ff-only
sudo -u reelbot .venv/bin/pip install --quiet -r requirements.txt
cp deploy/reel-bot.service /etc/systemd/system/reel-bot.service
systemctl daemon-reload && systemctl restart reel-bot
echo "Updated. Logs: journalctl -u reel-bot -f"
