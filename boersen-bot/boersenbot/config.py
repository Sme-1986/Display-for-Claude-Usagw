"""Lädt config.toml und stellt Standardwerte bereit."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROJEKT = Path(__file__).resolve().parent.parent


@dataclass
class Config:
    intervall_minuten: int = 30
    schwelle_stark: int = 65
    port: int = 8080
    web_adresse: str = ""
    datenbank: Path = PROJEKT / "daten" / "boersenbot.sqlite"

    news_cache_minuten: int = 120
    sec_user_agent: str = ""
    finnhub_key: str = ""
    apewisdom: bool = True

    anthropic_api_key: str = ""
    modell: str = "claude-opus-5-5"
    aufwand: str = "medium"
    max_websuchen: int = 5
    auto_analyse: bool = True

    ntfy_thema: str = ""
    ntfy_server: str = "https://ntfy.sh"

    extra: dict = field(default_factory=dict)

    @property
    def ki_aktiv(self) -> bool:
        return bool(self.anthropic_api_key)


def lade(pfad: Path | None = None) -> Config:
    pfad = pfad or Path(os.environ.get("BOERSENBOT_CONFIG", PROJEKT / "config.toml"))
    roh: dict = {}
    if pfad.exists():
        with open(pfad, "rb") as f:
            roh = tomllib.load(f)

    flach: dict = {}
    for abschnitt in roh.values():
        if isinstance(abschnitt, dict):
            flach.update(abschnitt)

    cfg = Config()
    for key, wert in flach.items():
        if hasattr(cfg, key):
            setattr(cfg, key, wert)
    cfg.datenbank = Path(cfg.datenbank)
    if not cfg.datenbank.is_absolute():
        cfg.datenbank = PROJEKT / cfg.datenbank
    cfg.anthropic_api_key = cfg.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    return cfg
