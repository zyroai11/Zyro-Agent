#!/usr/bin/env bash
# Install the Zyro Telegram bot as a service that starts on boot and restarts if it crashes.
# Run from the telegram-bot folder:  bash install-vps.sh
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME="$(whoami)"
cd "$DIR"

echo "==> Installing Python tools"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-venv python3-pip >/dev/null

echo "==> Creating the virtual environment"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt

if [ ! -f .env ]; then
  cp .env.example .env
  echo "!! No .env found. A blank one was created at $DIR/.env"
  echo "!! Copy your .env from the laptop (or fill this one in), then run this script again."
  exit 1
fi

echo "==> Creating the zyro-bot service"
sudo tee /etc/systemd/system/zyro-bot.service >/dev/null <<UNIT
[Unit]
Description=Zyro Telegram bot
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python $DIR/bot.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now zyro-bot
sleep 3
sudo systemctl --no-pager --lines=5 status zyro-bot || true
echo
echo "Done. The bot now runs on this server, starts on boot and restarts on crash."
echo "Logs:    sudo journalctl -u zyro-bot -f"
echo "Restart: sudo systemctl restart zyro-bot"
