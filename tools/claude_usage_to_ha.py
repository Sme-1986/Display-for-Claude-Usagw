#!/usr/bin/env python3
"""Meldet die Claude-Limits (5h-Session und Woche) als Sensoren an Home Assistant.

Zwei Betriebsarten:

  Statuszeile (empfohlen, nutzt nur dokumentierte Claude-Code-Daten):
      In ~/.claude/settings.json eintragen:
        "statusLine": {"type": "command",
                       "command": "python3 /pfad/zu/claude_usage_to_ha.py --statusline"}
      Claude Code uebergibt die Limits dann bei jeder Aktualisierung der Statuszeile.

  Abfrage im Hintergrund (auch wenn Claude Code gerade nicht laeuft):
      python3 claude_usage_to_ha.py --poll
      Nutzt den Login von Claude Code und einen nicht dokumentierten Endpunkt,
      der sich jederzeit aendern kann.

Home Assistant wird ueber Umgebungsvariablen HA_URL und HA_TOKEN konfiguriert
oder ueber ~/.config/claude-display.json: {"ha_url": "...", "ha_token": "..."}
"""
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

CONFIG = Path.home() / ".config" / "claude-display.json"
STAMP = Path.home() / ".cache" / "claude-display.stamp"
SENSORS = {
    "five_hour": ("sensor.claude_session_usage", "Claude Session (5h)"),
    "seven_day": ("sensor.claude_weekly_usage", "Claude Woche"),
}


def ha_config():
    cfg = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    url = os.environ.get("HA_URL") or cfg.get("ha_url")
    token = os.environ.get("HA_TOKEN") or cfg.get("ha_token")
    if not url or not token:
        raise SystemExit(f"HA_URL/HA_TOKEN fehlen (Umgebungsvariablen oder {CONFIG})")
    return url.rstrip("/"), token


def to_epoch(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())


def push(limits, timeout=5):
    """limits: {"five_hour": (prozent, resets_at), "seven_day": (...)}"""
    url, token = ha_config()
    for key, (entity, name) in SENSORS.items():
        if key not in limits or limits[key][0] is None:
            continue
        pct, resets = limits[key]
        body = {
            "state": round(float(pct), 1),
            "attributes": {
                "unit_of_measurement": "%",
                "friendly_name": name,
                "icon": "mdi:gauge",
                "resets_at": to_epoch(resets),
            },
        }
        req = urllib.request.Request(
            f"{url}/api/states/{entity}",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=timeout).read()


def statusline():
    data = json.load(sys.stdin)
    rl = data.get("rate_limits") or {}
    limits = {
        k: (rl[k].get("used_percentage"), rl[k].get("resets_at"))
        for k in SENSORS
        if isinstance(rl.get(k), dict)
    }
    parts = [data.get("model", {}).get("display_name", "Claude")]
    if "five_hour" in limits and limits["five_hour"][0] is not None:
        parts.append(f"5h {limits['five_hour'][0]:.0f}%")
    if "seven_day" in limits and limits["seven_day"][0] is not None:
        parts.append(f"Woche {limits['seven_day'][0]:.0f}%")
    print(" | ".join(parts))

    # Hoechstens alle 30 s senden und die Statuszeile nie blockieren
    try:
        if limits and (not STAMP.exists() or time.time() - STAMP.stat().st_mtime > 30):
            STAMP.parent.mkdir(parents=True, exist_ok=True)
            STAMP.touch()
            push(limits, timeout=2)
    except Exception:
        pass


def oauth_token():
    path = Path.home() / ".claude" / ".credentials.json"
    if path.exists():
        raw = path.read_text()
    else:  # macOS: Login liegt im Schluesselbund
        raw = subprocess.run(
            ["security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, check=True,
        ).stdout
    return json.loads(raw)["claudeAiOauth"]["accessToken"]


def poll_once():
    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={"Authorization": f"Bearer {oauth_token()}", "anthropic-beta": "oauth-2025-04-20"},
    )
    data = json.load(urllib.request.urlopen(req, timeout=10))
    limits = {
        k: (data[k].get("utilization"), data[k].get("resets_at"))
        for k in SENSORS
        if isinstance(data.get(k), dict)
    }
    push(limits)
    return limits


def main():
    if "--statusline" in sys.argv:
        return statusline()
    if "--poll" in sys.argv:
        while True:
            try:
                print(time.strftime("%H:%M:%S"), poll_once(), flush=True)
            except Exception as e:  # z.B. Login abgelaufen: Claude Code einmal starten
                print(time.strftime("%H:%M:%S"), "Fehler:", e, flush=True)
            time.sleep(180)
    print(poll_once())


if __name__ == "__main__":
    main()
