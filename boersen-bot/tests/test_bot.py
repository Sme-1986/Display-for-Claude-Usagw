"""Tests mit simulierten Daten – laufen ohne Internet: python -m pytest tests"""
import time

import numpy as np
import pandas as pd
import pytest

from boersenbot import quellen, scoring
from boersenbot.config import Config


def kurse_simulieren(trend=0.0, sprung=0.0, vol_faktor=1.0, n=260, seed=1):
    rng = np.random.default_rng(seed)
    r = rng.normal(0, 0.012, n)
    r[-20:] += trend  # Trend in den letzten 20 Tagen
    r[-1] += sprung
    close = 100 * np.cumprod(1 + r)
    idx = pd.bdate_range(end="2026-11-17", periods=n)
    vol = rng.normal(1e6, 1e5, n).clip(1e5)
    vol[-1] *= vol_faktor
    return pd.DataFrame(
        {"Open": close, "High": close * 1.006, "Low": close * 0.994, "Close": close, "Volume": vol},
        index=idx,
    )


def test_seitwaerts_ergibt_niedrigen_score():
    erg = scoring.berechne(kurse_simulieren(), bench=kurse_simulieren(seed=2))
    assert erg.score < 40


def test_starker_aufwaertstrend():
    df = kurse_simulieren(trend=0.012, sprung=0.06, vol_faktor=4)
    news = [{"titel": f"Firma übertrifft Erwartungen {i}", "zeit": time.time() - 3600, "stimmung": 1.0,
             "quelle": "Google News"} for i in range(12)]
    erg = scoring.berechne(df, bench=kurse_simulieren(seed=2), news=news,
                           social={"rang": 5, "rang_gestern": 40, "erwaehnungen": 300, "erwaehnungen_gestern": 50})
    assert erg.richtung == 1
    assert erg.score >= 65
    ausbruch = next(k for k in erg.komponenten if k["name"] == "Ausbruch")
    assert ausbruch["punkte"] > 0
    assert "Volumen ×" in " ".join(erg.flags)
    assert sum(k["max"] for k in erg.komponenten) == 100


def test_starker_abwaertstrend():
    erg = scoring.berechne(kurse_simulieren(trend=-0.012, sprung=-0.07, vol_faktor=3), bench=kurse_simulieren(seed=2))
    assert erg.richtung == -1
    assert erg.score >= 55


def test_stimmung():
    from boersenbot.stimmung import bewerte
    assert bewerte("SAP übertrifft Erwartungen, Aktie springt auf Rekordhoch") > 0
    assert bewerte("Gewinnwarnung: Aktie bricht ein") < 0
    assert bewerte("Hauptversammlung am Dienstag") == 0


@pytest.fixture
def bot(tmp_path, monkeypatch):
    from boersenbot.bot import Bot

    def fake_kurse(symbole, zeitraum="1y"):
        out = {}
        for i, s in enumerate(symbole):
            if s == "RHM.DE":
                out[s] = kurse_simulieren(trend=0.012, sprung=0.06, vol_faktor=4, seed=i)
            elif s == "BAYN.DE":
                out[s] = kurse_simulieren(trend=-0.01, sprung=-0.07, vol_faktor=3, seed=i)
            else:
                out[s] = kurse_simulieren(seed=i + 10)
        return out

    def fake_news(symbol, name):
        if symbol == "RHM.DE":
            return [quellen._item(symbol, quellen.Q_GOOGLE, f"Rheinmetall erhält Großauftrag – Aktie springt {i}",
                                  "https://example.com/" + str(i), time.time() - i * 3600) for i in range(12)]
        return []

    monkeypatch.setattr(quellen, "kurse", fake_kurse)
    monkeypatch.setattr(quellen, "google_news", fake_news)
    monkeypatch.setattr(quellen, "yahoo_news", lambda s: [])
    monkeypatch.setattr(quellen, "yahoo_rss", lambda s: [])
    monkeypatch.setattr(quellen, "naechste_zahlen", lambda s: None)
    monkeypatch.setattr(quellen, "apewisdom", lambda: {})
    cfg = Config(datenbank=tmp_path / "t.sqlite")
    b = Bot(cfg)
    b.lauf()
    return b


def test_durchlauf_und_web(bot):
    scores = bot.db.aktuelle_scores()
    assert len(scores) == len(bot.db.watchlist())
    top = scores[0]
    assert top["symbol"] in ("RHM.DE", "BAYN.DE")
    assert bot.db.schon_gemeldet("RHM.DE", time.strftime("%Y-%m-%d"))

    from boersenbot.web import erstelle_app
    c = erstelle_app(bot).test_client()
    for url in ["/", "/?filter=alle", "/?filter=ab", "/aktie/RHM.DE", "/watchlist", "/status", "/api/scores?stark=1"]:
        r = c.get(url)
        assert r.status_code == 200, url
    assert b"Rheinmetall" in c.get("/").data
    assert c.get("/api/scores?stark=1").json["aktien"]
    assert c.get("/aktie/GIBTSNICHT").status_code == 404
