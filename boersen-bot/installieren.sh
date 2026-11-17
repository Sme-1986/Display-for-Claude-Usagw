#!/usr/bin/env bash
# Installiert den Börsen-Bot auf einem Raspberry Pi (Raspberry Pi OS Bookworm oder neuer)
# und richtet ihn als Dienst ein, der beim Booten automatisch startet.
set -euo pipefail

ORDNER="$(cd "$(dirname "$0")" && pwd)"
BENUTZER="$(whoami)"

echo "==> Systempakete"
sudo apt-get update -qq
sudo apt-get install -y -qq python3-venv

echo "==> Python-Umgebung in $ORDNER/venv"
python3 -m venv "$ORDNER/venv"
"$ORDNER/venv/bin/pip" install -q --upgrade pip
"$ORDNER/venv/bin/pip" install -q -r "$ORDNER/requirements.txt"

if [ ! -f "$ORDNER/config.toml" ]; then
  cp "$ORDNER/config.example.toml" "$ORDNER/config.toml"
  echo "==> config.toml angelegt – bei Bedarf anpassen (API-Keys, Push)."
fi

echo "==> Dienst einrichten"
sudo tee /etc/systemd/system/boersenbot.service >/dev/null <<EOF
[Unit]
Description=Boersen-Bot
After=network-online.target
Wants=network-online.target

[Service]
User=$BENUTZER
WorkingDirectory=$ORDNER
ExecStart=$ORDNER/venv/bin/python $ORDNER/start.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now boersenbot

PORT=$(grep -E '^\s*port\s*=' "$ORDNER/config.toml" | head -1 | tr -dc '0-9')
IP=$(hostname -I | awk '{print $1}')
echo
echo "Fertig! Weboberfläche: http://$IP:${PORT:-8080}"
echo "Log ansehen:   journalctl -u boersenbot -f"
echo "Neu starten:   sudo systemctl restart boersenbot"
