"""Rebound-Chance nach starken Einbrüchen.

Idee: In 15 Jahren Kursgeschichte alle Einbrüche suchen, für jeden Merkmale zum
Zeitpunkt des Einbruchs berechnen (nur Daten bis zu diesem Tag!) und messen, ob sich
die Aktie danach erholt hat. Darauf wird eine logistische Regression trainiert.

  Einbruch: Schlusskurs liegt mindestens EINBRUCH_SIGMA normale Tagesschwankungen
            unter dem höchsten Schlusskurs der 5 Tage davor.
  Rebound:  Innerhalb von HORIZONT Handelstagen wird mindestens die Hälfte des
            Verlusts wieder aufgeholt.

Das Ergebnis ist eine historische Trefferquote, keine Garantie. Die Modellgüte wird an
den letzten Jahren geprüft, die beim Training nicht verwendet wurden.
"""
from __future__ import annotations

import logging
import math
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

EINBRUCH_SIGMA = 3.5
HORIZONT = 10
AUFHOLEN = 0.5
JAHRE = 15
TEST_JAHRE = 3
MIN_FAELLE = 300

# Merkmal -> (Beschriftung, Formatierung des Rohwerts)
MERKMALE: dict[str, tuple[str, str]] = {
    "einbruch": ("Stärke des Einbruchs", "{:.1f}σ"),
    "tag": ("Bewegung am letzten Tag", "{:+.1f}σ"),
    "trend": ("Trend in den 60 Tagen davor", "{:+.1f}σ"),
    "ma200": ("Abstand zur 200-Tage-Linie vorher", "{:+.0%}"),
    "rsi": ("RSI", "{:.0f}"),
    "volumen": ("Volumen", "{:.1f}× normal"),
    "markt": ("Index im selben Zeitraum", "{:+.1f}σ"),
    "relativ": ("Firmenspezifischer Anteil", "{:+.1f}σ"),
    "tief52": ("Abstand zum 52-Wochen-Tief", "{:+.0%}"),
}
SPALTEN = list(MERKMALE)


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    g = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    v = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + g / v.replace(0, np.nan))


def merkmale(df: pd.DataFrame, bench: pd.DataFrame | None) -> pd.DataFrame:
    """Merkmale für jeden Tag. Verwendet je Zeile nur Daten bis einschließlich dieses Tages."""
    close, vol = df["Close"], df["Volume"]
    ret = close.pct_change()
    sigma = ret.rolling(60).std().shift(6)  # Schwankung VOR dem Einbruch
    ref = close.shift(1).rolling(5).max()
    drop = close / ref - 1
    vor = close.shift(6)

    if bench is not None and len(bench) > 100:
        b = bench["Close"].reindex(close.index).ffill()
        b_sigma = b.pct_change().rolling(60).std().shift(6)
        b_drop = b / b.shift(1).rolling(5).max() - 1
        markt = b_drop / b_sigma
        relativ = (drop - b_drop) / sigma
    else:
        markt = pd.Series(0.0, index=close.index)
        relativ = drop / sigma

    vol_basis = vol.shift(1).rolling(20).median().replace(0, np.nan)
    m = pd.DataFrame(
        {
            "einbruch": -drop / sigma,
            "tag": ret / sigma,
            "trend": (vor / close.shift(66) - 1) / (sigma * math.sqrt(60)),
            "ma200": vor / vor.rolling(200).mean() - 1,
            "rsi": _rsi(close),
            "volumen": np.log((vol / vol_basis).clip(lower=0.05)),
            "markt": markt,
            "relativ": relativ,
            "tief52": close / df["Low"].rolling(252, min_periods=120).min() - 1,
        },
        index=close.index,
    )
    m["_drop"] = drop
    m["_ref"] = ref
    return m.replace([np.inf, -np.inf], np.nan)


def faelle(df: pd.DataFrame, bench: pd.DataFrame | None) -> pd.DataFrame:
    """Historische Einbrüche mit Ergebnis (1 = Rebound)."""
    m = merkmale(df, bench)
    close = df["Close"]
    zukunft_max = close[::-1].rolling(HORIZONT, min_periods=HORIZONT).max()[::-1].shift(-1)
    ziel = close + AUFHOLEN * (m["_ref"] - close)
    m["rebound"] = (zukunft_max >= ziel).astype(float)
    m.loc[zukunft_max.isna(), "rebound"] = np.nan

    ist = m["einbruch"] >= EINBRUCH_SIGMA
    # Aus einer Serie zusammenhängender Einbruchstage nur höchstens jeden 5. Tag nehmen,
    # sonst zählt ein Absturz mehrfach
    auswahl, letzter = [], -10
    for i, flag in enumerate(ist.to_numpy()):
        if flag and i - letzter >= 5:
            auswahl.append(i)
            letzter = i
    f = m.iloc[auswahl].dropna(subset=SPALTEN + ["rebound"])
    return f[SPALTEN + ["rebound"]]


# ------------------------------------------------------------------ Modell
def _logreg(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iter_: int = 50) -> np.ndarray:
    """Logistische Regression (Newton-Verfahren, L2-Regularisierung). Gibt [b0, b1, …] zurück."""
    Xb = np.hstack([np.ones((len(X), 1)), X])
    w = np.zeros(Xb.shape[1])
    reg = np.eye(len(w)) * l2
    reg[0, 0] = 0
    for _ in range(iter_):
        p = 1 / (1 + np.exp(-Xb @ w))
        grad = Xb.T @ (p - y) + reg @ w
        H = (Xb * (p * (1 - p))[:, None]).T @ Xb + reg
        schritt = np.linalg.solve(H, grad)
        w -= schritt
        if np.abs(schritt).max() < 1e-6:
            break
    return w


def _vorhersage(w: np.ndarray, X: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-(w[0] + X @ w[1:])))


def _auc(y: np.ndarray, p: np.ndarray) -> float:
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    raenge = pd.Series(np.concatenate([pos, neg])).rank().to_numpy()
    return float((raenge[: len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def trainieren(daten: dict[str, pd.DataFrame], benchmarks: dict[str, str]) -> dict | None:
    """daten: Symbol -> OHLCV (auch die Indizes), benchmarks: Symbol -> Index-Symbol."""
    teile = []
    for s, df in daten.items():
        if s not in benchmarks or len(df) < 300:
            continue
        f = faelle(df, daten.get(benchmarks[s]))
        if len(f):
            f = f.assign(symbol=s)
            teile.append(f)
    if not teile:
        return None
    alle = pd.concat(teile).sort_index()
    if len(alle) < MIN_FAELLE:
        log.info("Rebound: nur %d Fälle – zu wenig", len(alle))
        return {"ok": False, "faelle": len(alle), "trainiert": time.time()}

    grenze = pd.Timestamp(date.today() - timedelta(days=365 * TEST_JAHRE))
    idx = alle.index.tz_localize(None) if alle.index.tz is not None else alle.index
    train, test = alle[idx < grenze], alle[idx >= grenze]

    def fit(teil: pd.DataFrame):
        X = teil[SPALTEN].to_numpy(float)
        mu, sd = X.mean(0), X.std(0)
        sd[sd == 0] = 1
        return mu, sd, _logreg((X - mu) / sd, teil["rebound"].to_numpy(float))

    guete: dict = {}
    if len(train) >= MIN_FAELLE // 2 and len(test) >= 50:
        mu, sd, w = fit(train)
        Xt = (test[SPALTEN].to_numpy(float) - mu) / sd
        yt = test["rebound"].to_numpy(float)
        p = _vorhersage(w, Xt)
        basis = float(train["rebound"].mean())
        brier = float(np.mean((p - yt) ** 2))
        brier_basis = float(np.mean((basis - yt) ** 2))
        oben = yt[p >= np.quantile(p, 2 / 3)]
        unten = yt[p <= np.quantile(p, 1 / 3)]
        guete = {
            "test_faelle": int(len(test)),
            "test_basis": float(yt.mean()),
            "brier": brier,
            "brier_basis": brier_basis,
            "verbesserung": 1 - brier / brier_basis if brier_basis else 0.0,
            "auc": _auc(yt, p),
            "quote_oben": float(oben.mean()) if len(oben) else None,
            "quote_unten": float(unten.mean()) if len(unten) else None,
        }

    mu, sd, w = fit(alle)  # Endgültiges Modell mit allen Daten
    return {
        "ok": True,
        "trainiert": time.time(),
        "faelle": int(len(alle)),
        "aktien": int(alle["symbol"].nunique()),
        "seit": str(idx.min().date()),
        "basis": float(alle["rebound"].mean()),
        "mu": mu.tolist(),
        "sd": sd.tolist(),
        "w": w.tolist(),
        "guete": guete,
        "einstellungen": {"einbruch_sigma": EINBRUCH_SIGMA, "horizont": HORIZONT, "aufholen": AUFHOLEN},
    }


def modell_taugt(modell: dict | None) -> bool:
    g = (modell or {}).get("guete") or {}
    return bool(g) and g.get("verbesserung", 0) > 0.005 and (g.get("auc") or 0) > 0.55


def bewerte(modell: dict | None, df: pd.DataFrame, bench: pd.DataFrame | None) -> dict | None:
    """Rebound-Chance für den aktuellen Tag – nur wenn gerade ein Einbruch vorliegt."""
    if not modell or not modell.get("ok"):
        return None
    m = merkmale(df, bench).iloc[-1]
    if not (m["einbruch"] >= EINBRUCH_SIGMA) or m[SPALTEN].isna().any():
        return None
    mu, sd, w = np.array(modell["mu"]), np.array(modell["sd"]), np.array(modell["w"])
    x = (m[SPALTEN].to_numpy(float) - mu) / sd
    chance = float(_vorhersage(w, x[None, :])[0])

    beitraege = w[1:] * x
    faktoren = []
    for name, b, roh in zip(SPALTEN, beitraege, m[SPALTEN]):
        if abs(b) < 0.08:
            continue
        label, fmt = MERKMALE[name]
        wert = math.exp(roh) if name == "volumen" else roh
        faktoren.append({"text": f"{label}: {fmt.format(wert)}", "wirkung": round(float(b), 2)})
    faktoren.sort(key=lambda f: -abs(f["wirkung"]))

    return {
        "chance": chance,
        "basis": modell["basis"],
        "faelle": modell["faelle"],
        "seit": modell["seit"],
        "horizont": HORIZONT,
        "verlust": float(m["_drop"]),
        "ziel": float(df["Close"].iloc[-1] + AUFHOLEN * (m["_ref"] - df["Close"].iloc[-1])),
        "dafuer": [f for f in faktoren if f["wirkung"] > 0][:4],
        "dagegen": [f for f in faktoren if f["wirkung"] < 0][:4],
        "verlaesslich": modell_taugt(modell),
    }
