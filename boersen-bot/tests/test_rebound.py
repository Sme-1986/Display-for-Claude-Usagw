"""Rebound-Modell mit künstlichen Daten, in denen die Regel bekannt ist:
Markt-Crashs erholen sich, firmenspezifische Abstürze nicht."""
import numpy as np
import pandas as pd

from boersenbot import rebound


def welt(n_aktien=12, tage=3000, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=tage)
    m_ret = rng.normal(0.0003, 0.009, tage)
    for t in rng.choice(np.arange(300, tage - 20), 40, replace=False):
        m_ret[t] -= 0.06            # Markt-Crash …
        m_ret[t + 1 : t + 6] += 0.012  # … der sich in den Folgetagen erholt
    markt = 100 * np.cumprod(1 + m_ret)

    def ohlcv(close, vol):
        return pd.DataFrame({"Open": close, "High": close * 1.005, "Low": close * 0.995,
                             "Close": close, "Volume": vol}, index=idx)

    daten = {"^IDX": ohlcv(markt, np.full(tage, 1e9))}
    for i in range(n_aktien):
        r = m_ret + rng.normal(0, 0.012, tage)
        for t in rng.choice(np.arange(300, tage - 20), 25, replace=False):
            r[t] -= 0.10             # firmenspezifischer Absturz ohne Erholung
            r[t + 1 : t + 6] -= 0.004
        vol = rng.normal(1e6, 1e5, tage).clip(1e5)
        daten[f"A{i}"] = ohlcv(100 * np.cumprod(1 + r), vol)
    return daten, {f"A{i}": "^IDX" for i in range(n_aktien)}


def test_modell_lernt_regel():
    daten, bench = welt()
    m = rebound.trainieren(daten, bench)
    assert m["ok"] and m["faelle"] >= rebound.MIN_FAELLE
    g = m["guete"]
    assert g["auc"] > 0.6, g
    assert g["verbesserung"] > 0, g
    assert g["quote_oben"] > g["quote_unten"]
    # Je größer der firmenspezifische Anteil am Einbruch (stark negativer Wert),
    # desto seltener der Rebound → positives Gewicht
    w_relativ = m["w"][1 + rebound.SPALTEN.index("relativ")]
    assert w_relativ > 0.5


def test_bewerten_nur_bei_einbruch():
    daten, bench = welt(n_aktien=8)
    m = rebound.trainieren(daten, bench)
    df = daten["A0"]
    assert rebound.bewerte(m, df, daten["^IDX"]) is None or df["Close"].iloc[-1] < df["Close"].iloc[-6:-1].max()

    # Künstlicher Markt-Crash am letzten Tag → Rebound-Chance über dem Durchschnitt
    crash = {k: v.copy() for k, v in daten.items()}
    for k in crash:
        for spalte in ("Open", "High", "Low", "Close"):
            crash[k].iloc[-1, crash[k].columns.get_loc(spalte)] *= 0.92
    rb_markt = rebound.bewerte(m, crash["A0"], crash["^IDX"])
    assert rb_markt is not None
    assert 0 < rb_markt["chance"] < 1

    # Gleicher Einbruch, aber nur die Aktie fällt → geringere Chance
    allein = {k: v.copy() for k, v in daten.items()}
    for spalte in ("Open", "High", "Low", "Close"):
        allein["A0"].iloc[-1, allein["A0"].columns.get_loc(spalte)] *= 0.92
    rb_allein = rebound.bewerte(m, allein["A0"], allein["^IDX"])
    assert rb_allein is not None
    assert rb_markt["chance"] > rb_allein["chance"]
    assert rb_markt["dafuer"]
