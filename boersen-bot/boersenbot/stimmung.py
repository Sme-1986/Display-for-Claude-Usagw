"""Sehr einfache Stimmungsbewertung von Schlagzeilen (Deutsch + Englisch).

Bewusst ohne große ML-Modelle, damit es auf dem Raspberry Pi schnell läuft.
Ergebnis: -1 (negativ) … +1 (positiv). Die eigentliche Begründung macht die KI.
"""
from __future__ import annotations

import re

POSITIV = {
    # Englisch
    "beat", "beats", "surge", "surges", "soar", "soars", "jump", "jumps", "rally", "rallies",
    "record", "upgrade", "upgraded", "outperform", "buy", "raises", "raised", "boost",
    "strong", "growth", "profit", "gain", "gains", "tops", "exceeds", "bullish", "approval",
    "approved", "wins", "contract", "partnership", "breakthrough", "climbs", "higher",
    "rebound", "dividend", "buyback", "upbeat",
    # Deutsch
    "steigt", "steigen", "springt", "klettert", "rekord", "rekordhoch", "hochgestuft",
    "kaufempfehlung", "kaufen", "übertrifft", "gewinn", "gewinnsprung", "wachstum", "stark",
    "starke", "anhebung", "hebt", "erhöht", "auftrag", "großauftrag", "zulassung", "plus",
    "rally", "erholung", "dividende", "aktienrückkauf", "zuversichtlich", "kursziel",
}

NEGATIV = {
    # Englisch
    "miss", "misses", "missed", "plunge", "plunges", "slump", "slumps", "drop", "drops",
    "fall", "falls", "tumble", "tumbles", "downgrade", "downgraded", "underperform", "sell",
    "cut", "cuts", "lowers", "lowered", "weak", "loss", "losses", "warning", "warns",
    "lawsuit", "probe", "investigation", "recall", "bearish", "layoffs", "fraud", "lower",
    "sinks", "crash", "delay", "delayed", "fine", "fined", "bankruptcy", "slashes",
    # Deutsch
    "fällt", "fallen", "sinkt", "sinken", "bricht", "einbruch", "absturz", "abgestuft",
    "verkaufen", "verkaufsempfehlung", "verfehlt", "verlust", "verluste", "schwach",
    "schwache", "senkt", "gesenkt", "warnung", "gewinnwarnung", "klage", "ermittlungen",
    "rückruf", "stellenabbau", "minus", "pleite", "insolvenz", "kursrutsch", "strafe",
    "verzögerung", "belastet", "enttäuscht", "enttäuschend",
}

VERNEINUNG = {"not", "no", "nicht", "kein", "keine", "ohne"}

_WORT = re.compile(r"[a-zäöüß]+")


def bewerte(text: str) -> float:
    woerter = _WORT.findall(text.lower())
    if not woerter:
        return 0.0
    summe = 0
    for i, w in enumerate(woerter):
        wert = 1 if w in POSITIV else -1 if w in NEGATIV else 0
        if wert and i > 0 and woerter[i - 1] in VERNEINUNG:
            wert = -wert
        summe += wert
    if summe == 0:
        return 0.0
    return max(-1.0, min(1.0, summe / 2))
