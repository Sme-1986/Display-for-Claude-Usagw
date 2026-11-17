"""KI-Recherche: Warum bewegt sich die Aktie? (Claude API mit Websuche)"""
from __future__ import annotations

import logging
from datetime import datetime

import anthropic

from .config import Config

log = logging.getLogger(__name__)

SYSTEM = """Du bist ein nüchterner Finanz-Rechercheur. Du bekommst eine Aktie, die gerade \
einen auffällig starken Trend zeigt, samt Kennzahlen und gesammelten Schlagzeilen. \
Finde heraus, WARUM sich der Kurs so bewegt.

Regeln:
- Nutze die Websuche, um die Schlagzeilen zu prüfen und fehlende Gründe zu finden \
(Quartalszahlen, Prognosen, Analysten, Übernahmen, Aufträge, Regulierung, Sektor- oder \
Makro-Nachrichten, Gerüchte).
- Nenne nur Gründe, die du mit einer Quelle belegen kannst. Wenn nichts Konkretes zu \
finden ist, schreib das ehrlich (z. B. "kein eindeutiger Auslöser, vermutlich Sektorbewegung").
- Unterscheide Fakten von Vermutungen.
- Keine Kauf- oder Verkaufsempfehlung.

Antworte auf Deutsch, kurz und gegliedert, ohne Einleitung:
Kurzfazit: <ein Satz>
Gründe:
- <Grund> [Quelle: <Medium>, <Datum>]
Auslöser: <genau eins von: Gesamtmarkt/Sektor | Firma, eher einmalig | Firma, grundlegend | unklar>
Einordnung: <1–3 Sätze: einmaliges Ereignis oder anhaltender Trend? Was als Nächstes wichtig wird (Termine)?>
Sicherheit: <hoch | mittel | niedrig> – <kurze Begründung>"""


def _prompt(symbol: str, name: str, score: dict, news: list[dict]) -> str:
    k = score["details"]["kennzahlen"]
    richtung = {1: "AUFWÄRTS", -1: "ABWÄRTS", 0: "unklar"}[score["richtung"]]
    zeilen = [
        f"Aktie: {name} ({symbol})",
        f"Datum: {datetime.now():%d.%m.%Y %H:%M}",
        f"Trend-Score: {score['score']}/100, Richtung: {richtung}",
        f"Kurs: {score['kurs']:.2f}, heute {k['rendite_1d']:+.2%}, 5 Tage {k['rendite_5d']:+.2%}, "
        f"20 Tage {k['rendite_20d']:+.2%}",
        f"Volumen: {k['volumen_faktor']:.1f}× normal, ADX {k['adx']:.0f}, RSI {k['rsi']:.0f}",
        f"Auffälligkeiten: {', '.join(score['details']['flags']) or 'keine'}",
    ]
    rb = score["details"].get("rebound")
    if rb:
        zeilen.append(
            f"Statistik: Nach ähnlichen Einbrüchen erholten sich Aktien in {rb['chance']:.0%} der Fälle "
            f"binnen {rb['horizont']} Handelstagen um mind. die Hälfte (Durchschnitt aller Einbrüche: "
            f"{rb['basis']:.0%}). Ordne kurz ein, ob der Auslöser eher für oder gegen eine Erholung spricht."
        )
    if k.get("zahlen_termin"):
        zeilen.append(f"Quartalszahlen-Termin laut Yahoo: {k['zahlen_termin']}")
    zeilen.append("\nGesammelte Schlagzeilen (neueste zuerst):")
    for n in news[:40]:
        zeit = datetime.fromtimestamp(n["zeit"]).strftime("%d.%m. %H:%M")
        zeilen.append(f"- [{zeit}, {n['quelle']}] {n['titel']}")
    if not news:
        zeilen.append("- (keine Schlagzeilen gefunden)")
    return "\n".join(zeilen)


def recherchiere(cfg: Config, symbol: str, name: str, score: dict, news: list[dict]) -> tuple[str, list[dict]]:
    """Gibt (Text, Quellen) zurück. Quellen = [{titel, url}]."""
    client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
    messages: list[dict] = [{"role": "user", "content": _prompt(symbol, name, score, news)}]
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": cfg.max_websuchen}]

    antwort = None
    for _ in range(4):  # pause_turn: lange Websuchen werden vom Server in Etappen geliefert
        antwort = client.beta.messages.create(
            model=cfg.modell,
            max_tokens=16000,
            system=SYSTEM,
            messages=messages,
            tools=tools,
            output_config={"effort": cfg.aufwand},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if antwort.stop_reason != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": antwort.content}]

    if antwort.stop_reason == "refusal":
        return "Die KI hat diese Anfrage abgelehnt. Bitte die Schlagzeilen manuell prüfen.", []

    texte: list[str] = []
    quellen: dict[str, str] = {}  # tatsächlich zitierte Quellen
    gefunden: dict[str, str] = {}  # alle Suchtreffer (Ersatz, falls nichts zitiert wurde)
    for block in antwort.content:
        if block.type == "text":
            texte.append(block.text)
            for c in getattr(block, "citations", None) or []:
                url = getattr(c, "url", None)
                if url:
                    quellen.setdefault(url, getattr(c, "title", None) or url)
        elif block.type == "web_search_tool_result" and isinstance(block.content, list):
            for r in block.content:
                if getattr(r, "url", None):
                    gefunden.setdefault(r.url, r.title or r.url)
    if not quellen:
        quellen = dict(list(gefunden.items())[:10])

    text = "".join(texte).strip() or "Keine Antwort erhalten."
    return text, [{"titel": t, "url": u} for u, t in quellen.items()]
