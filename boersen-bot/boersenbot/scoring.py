"""Trend-Score 0–100 aus Kursdaten, Nachrichten und Social-Media.

Der Score misst die STÄRKE eines Trends, die Richtung (+1 hoch / -1 runter / 0 unklar)
wird separat ausgegeben. Jede Komponente hat eine Maximalpunktzahl, damit man in der
Oberfläche sieht, woher der Score kommt.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd


def _clip01(x: float) -> float:
    if x is None or math.isnan(x):
        return 0.0
    return max(0.0, min(1.0, x))


def adx(df: pd.DataFrame, n: int = 14) -> float:
    """Average Directional Index nach Wilder."""
    h, l, c = df["High"], df["Low"], df["Close"]
    up = h.diff()
    down = -l.diff()
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    alpha = 1 / n
    atr = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=alpha, adjust=False).mean() / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    wert = dx.ewm(alpha=alpha, adjust=False).mean().iloc[-1]
    return float(wert) if not math.isnan(wert) else 0.0


def rsi(close: pd.Series, n: int = 14) -> float:
    delta = close.diff()
    gewinn = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    verlust = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gewinn.iloc[-1] / verlust.iloc[-1] if verlust.iloc[-1] else float("inf")
    return float(100 - 100 / (1 + rs))


def _ret(close: pd.Series, n: int) -> float:
    if len(close) <= n:
        return 0.0
    return float(close.iloc[-1] / close.iloc[-1 - n] - 1)


@dataclass
class Ergebnis:
    score: int
    richtung: int
    kurs: float
    chg_1d: float
    chg_20d: float
    komponenten: list[dict] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    kennzahlen: dict = field(default_factory=dict)

    def details(self) -> dict:
        return {"komponenten": self.komponenten, "flags": self.flags, "kennzahlen": self.kennzahlen}


def berechne(
    df: pd.DataFrame,
    bench: pd.DataFrame | None = None,
    news: list[dict] | None = None,
    social: dict | None = None,
    zahlen_termin: str | None = None,
    jetzt: float | None = None,
) -> Ergebnis:
    jetzt = jetzt or time.time()
    news = news or []
    close = df["Close"]
    vol = df["Volume"]
    renditen = close.pct_change().dropna()

    # Normale Tagesschwankung (ohne die letzten 5 Tage, damit ein Ausreißer sich nicht selbst normalisiert)
    basis = renditen.iloc[-65:-5] if len(renditen) > 70 else renditen.iloc[:-1]
    sigma = float(basis.std()) or 0.01

    r1, r5, r20 = _ret(close, 1), _ret(close, 5), _ret(close, 20)
    z1 = r1 / sigma
    z5 = r5 / (sigma * math.sqrt(5))
    z20 = r20 / (sigma * math.sqrt(20))

    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else float("nan")
    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else float("nan")
    kurs = float(close.iloc[-1])

    # Richtung: gewichtetes Momentum
    roh = 0.5 * z20 + 0.3 * z5 + 0.2 * z1
    richtung = 0 if abs(roh) < 0.4 else (1 if roh > 0 else -1)

    komp: list[dict] = []
    flags: list[str] = []

    def add(name: str, punkte: float, maximum: int, text: str) -> None:
        komp.append({"name": name, "punkte": round(punkte, 1), "max": maximum, "text": text})

    # 1) Momentum
    p = _clip01(abs(z20) / 2.5) * 12 + _clip01(abs(z5) / 2.5) * 8
    add("Momentum", p, 20, f"20 T: {r20:+.1%} ({z20:+.1f}σ), 5 T: {r5:+.1%} ({z5:+.1f}σ)")

    # 2) Heutige Bewegung
    p = _clip01((abs(z1) - 1) / 3) * 10
    add("Tagesbewegung", p, 10, f"{r1:+.2%} = {z1:+.1f}× normale Schwankung")

    # 3) Volumen (heute evtl. noch unvollständig → Maximum aus heute/gestern)
    vol_basis = float(vol.iloc[-22:-2].median()) or 1.0
    vol_ratio = max(float(vol.iloc[-1]), float(vol.iloc[-2])) / vol_basis
    p = _clip01((vol_ratio - 1) / 2) * 15
    add("Volumen", p, 15, f"{vol_ratio:.1f}× des üblichen Handelsvolumens")
    if vol_ratio >= 2.5:
        flags.append(f"Volumen ×{vol_ratio:.1f}")

    # 4) Ausbruch (nur in Trendrichtung)
    fenster = df.iloc[-253:-1]
    hoch52, tief52 = float(fenster["High"].max()), float(fenster["Low"].min())
    hoch20, tief20 = float(df["High"].iloc[-21:-1].max()), float(df["Low"].iloc[-21:-1].min())
    p, text = 0.0, "kein Ausbruch"
    if richtung >= 0 and kurs >= hoch52 * 0.99:
        p, text = 10, f"nahe/über 52-Wochen-Hoch ({hoch52:.2f})"
        flags.append("52W-Hoch")
    elif richtung <= 0 and kurs <= tief52 * 1.01:
        p, text = 10, f"nahe/unter 52-Wochen-Tief ({tief52:.2f})"
        flags.append("52W-Tief")
    elif richtung > 0 and kurs > hoch20:
        p, text = 5, f"über 20-Tage-Hoch ({hoch20:.2f})"
    elif richtung < 0 and kurs < tief20:
        p, text = 5, f"unter 20-Tage-Tief ({tief20:.2f})"
    add("Ausbruch", p, 10, text)

    # 5) Trendstruktur über gleitende Durchschnitte
    p, text = 0.0, "keine klare Ordnung"
    if not math.isnan(ma50):
        if richtung >= 0 and kurs > ma20 > ma50 and (math.isnan(ma200) or ma50 > ma200):
            p, text = 10, "Kurs > MA20 > MA50 > MA200"
        elif richtung <= 0 and kurs < ma20 < ma50 and (math.isnan(ma200) or ma50 < ma200):
            p, text = 10, "Kurs < MA20 < MA50 < MA200"
        elif richtung > 0 and kurs > ma50:
            p, text = 5, "Kurs über MA50"
        elif richtung < 0 and kurs < ma50:
            p, text = 5, "Kurs unter MA50"
    add("Trendstruktur", p, 10, text)

    # 6) ADX
    adx_wert = adx(df.iloc[-150:])
    p = _clip01((adx_wert - 15) / 25) * 10
    add("Trendstärke (ADX)", p, 10, f"ADX {adx_wert:.0f} (ab 25 = klarer Trend)")

    # 7) Relative Stärke zum Index
    rs_z = 0.0
    if bench is not None and len(bench) > 21:
        rs = r20 - _ret(bench["Close"], 20)
        rs_z = rs / (sigma * math.sqrt(20))
        gleich = richtung == 0 or (rs_z > 0) == (richtung > 0)
        p = _clip01(abs(rs_z) / 2) * 10 if gleich else 0.0
        add("Relative Stärke", p, 10, f"{rs:+.1%} vs. Index in 20 Tagen")
    else:
        add("Relative Stärke", 0, 10, "kein Index verfügbar")

    # 8) Nachrichten
    vor48 = jetzt - 48 * 3600
    frische = [n for n in news if n["zeit"] >= vor48]
    titel = {n["titel"].lower()[:60] for n in frische}
    anzahl = len(titel)
    stimmung = float(np.mean([n["stimmung"] for n in frische])) if frische else 0.0
    sec = [n for n in news if n["quelle"] == "SEC EDGAR" and n["zeit"] >= jetzt - 3 * 86400]
    p = _clip01(anzahl / 15) * 5
    if richtung and stimmung * richtung > 0:
        p += _clip01(abs(stimmung) / 0.4) * 3
    if sec:
        p += 2
        flags.append("SEC-Meldung")
    p = min(p, 10)
    add("Nachrichten", p, 10, f"{anzahl} Meldungen in 48 h, Stimmung {stimmung:+.2f}"
        + (f", {len(sec)} SEC-Meldung(en)" if sec else ""))
    if anzahl >= 10:
        flags.append("News-Welle")

    # 9) Social Media
    if social:
        m, mg, rang = social["erwaehnungen"], social["erwaehnungen_gestern"], social["rang"]
        anstieg = m / max(mg, 1)
        p = _clip01((anstieg - 1) / 2) * 3 + (2 if rang <= 20 else 1 if rang <= 50 else 0)
        add("Reddit", p, 5, f"Rang {rang}, {m} Erwähnungen (gestern {mg})")
        if anstieg >= 3 and m >= 20:
            flags.append("Reddit-Hype")
    else:
        add("Reddit", 0, 5, "nicht unter den meistdiskutierten Aktien")

    # Zahlen-Termin als Hinweis (kein Score, erklärt aber oft die Bewegung)
    if zahlen_termin:
        try:
            tage = (date.fromisoformat(zahlen_termin[:10]) - date.fromtimestamp(jetzt)).days
            if -3 <= tage <= 7:
                flags.append("Zahlen heute" if tage == 0 else f"Zahlen {'vor' if tage < 0 else 'in'} {abs(tage)} T")
        except ValueError:
            pass

    gesamt = int(round(sum(k["punkte"] for k in komp)))
    gesamt = max(0, min(100, gesamt))

    kennzahlen = {
        "rendite_1d": r1, "rendite_5d": r5, "rendite_20d": r20,
        "sigma": sigma, "volumen_faktor": vol_ratio, "adx": adx_wert,
        "rsi": rsi(close), "ma20": ma20, "ma50": ma50, "ma200": ma200,
        "hoch52": hoch52, "tief52": tief52, "rs_z": rs_z,
        "news_48h": anzahl, "stimmung": stimmung, "zahlen_termin": zahlen_termin,
    }
    kennzahlen = {k: (None if isinstance(v, float) and math.isnan(v) else v) for k, v in kennzahlen.items()}

    return Ergebnis(gesamt, richtung, kurs, r1, r20, komp, flags, kennzahlen)
