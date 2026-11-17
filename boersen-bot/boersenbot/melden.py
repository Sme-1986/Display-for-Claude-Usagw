"""Push-Benachrichtigung über ntfy.sh (kostenlos, App für Android/iOS)."""
from __future__ import annotations

import logging

import requests

from .config import Config

log = logging.getLogger(__name__)


def push(cfg: Config, titel: str, text: str, link: str | None = None) -> None:
    if not cfg.ntfy_thema:
        return
    nachricht = {"topic": cfg.ntfy_thema, "title": titel, "message": text, "tags": ["chart_with_upwards_trend"]}
    if link:
        nachricht["click"] = link
    try:
        requests.post(cfg.ntfy_server.rstrip("/"), json=nachricht, timeout=10)
    except Exception as e:  # noqa: BLE001
        log.warning("ntfy: %s", e)
