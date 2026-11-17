# Börsen-Bot für den Raspberry Pi

Sammelt regelmäßig Kurse und Nachrichten aus kostenlosen Quellen, gibt jeder Aktie einen
**Trend-Score von 0–100** und zeigt alles in einer Weboberfläche im Heimnetz.
Bei starken Trends recherchiert auf Wunsch eine KI (Claude) die **Gründe** – mit Quellen.

## Was er macht

1. **Alle 30 Minuten** (einstellbar) werden alle Quellen abgefragt.
2. Für jede Aktie der Watchlist wird ein **Score** berechnet (siehe unten).
3. Ab Score **65** (einstellbar) gilt ein Trend als **stark**:
   - Die KI sucht im Web nach den Gründen (falls API-Key eingetragen).
   - Optional kommt eine **Push-Nachricht** aufs Handy (ntfy).
   - Pro Aktie höchstens einmal am Tag – kein Dauer-Gepiepe.
4. Die **Weboberfläche** zeigt die starken Trends, alle Aktien, Details, Schlagzeilen und die KI-Begründung.

Start-Watchlist: alle **DAX-40**-Werte + 15 große **US-Aktien**. In der Oberfläche änderbar.

## Kostenlose Quellen

| Quelle | Liefert | Key nötig? |
|---|---|---|
| Yahoo Finance (`yfinance`) | Tageskurse + Volumen (1 Jahr), Nachrichten, Termine für Quartalszahlen | nein |
| Yahoo Finance RSS | Schlagzeilen je Aktie | nein |
| Google News RSS | Schlagzeilen (deutsch für `.DE`-Aktien, sonst englisch) | nein |
| SEC EDGAR | US-Pflichtmitteilungen (8-K: Zahlen, Übernahmen, Managementwechsel …) | nein, nur Kontakt im User-Agent |
| ApeWisdom | Wie oft eine Aktie auf Reddit (wallstreetbets & Co.) erwähnt wird | nein |
| Finnhub | Zusätzliche US-Firmennachrichten | ja, kostenlos |
| Claude API | KI-Recherche der Gründe (mit Websuche) | ja, kostenpflichtig (Cent-Beträge) |

Fällt eine Quelle aus, läuft der Rest einfach weiter.

## Der Score (0–100)

Der Score misst die **Stärke** eines Trends, der Pfeil ▲/▼ zeigt die **Richtung**.

| Baustein | Max. | Was zählt |
|---|---|---|
| Momentum | 20 | Rendite über 5 und 20 Tage im Verhältnis zur normalen Schwankung der Aktie |
| Tagesbewegung | 10 | Wie ungewöhnlich ist die heutige Bewegung? |
| Volumen | 15 | Handelsvolumen im Vergleich zum Durchschnitt – wichtigster Filter gegen Zufallsrauschen |
| Ausbruch | 10 | Neues 52-Wochen-Hoch/-Tief bzw. 20-Tage-Ausbruch in Trendrichtung |
| Trendstruktur | 10 | Kurs, 20-, 50- und 200-Tage-Linie in sauberer Reihenfolge |
| Trendstärke (ADX) | 10 | Klassischer Indikator für Trendstärke |
| Relative Stärke | 10 | Läuft die Aktie anders als ihr Index (DAX bzw. S&P 500)? → firmenspezifischer Grund |
| Nachrichten | 10 | Anzahl der Meldungen in 48 h, Stimmung passend zur Richtung, SEC-Meldungen |
| Reddit | 5 | Rang und Anstieg der Erwähnungen |

Zusätzlich gibt es Hinweise wie **„Zahlen in 2 T“**, **„52W-Hoch“**, **„Volumen ×3.4“** oder **„Reddit-Hype“**.
Auf der Detailseite jeder Aktie steht, wie viele Punkte aus welchem Baustein kommen.

## Rebound-Chance nach Einbrüchen

Fällt eine Aktie stark (mindestens 3,5× ihre normale Tagesschwankung unter das 5-Tage-Hoch),
zeigt der Bot eine **Rebound-Chance**: Wie oft haben sich Aktien in ähnlichen Situationen
innerhalb von **10 Handelstagen um mindestens die Hälfte des Verlusts** erholt?

- **Datenbasis:** 15 Jahre Tageskurse aller Watchlist-Aktien, wöchentlich neu ausgewertet.
- **Modell:** logistische Regression auf 9 Merkmalen, darunter Stärke des Einbruchs, Trend davor,
  Abstand zur 200-Tage-Linie, RSI, Volumen, Index im selben Zeitraum und firmenspezifischer Anteil.
- **Ehrlichkeitscheck:** Das Modell wird an den letzten 3 Jahren getestet, die es beim Training nicht
  gesehen hat. Ist es dort kaum besser als der reine Durchschnitt, steht ein Warnhinweis an der Zahl.
  Die Testergebnisse stehen unter **Quellen → Rebound-Modell**.
- Neben der Zahl stehen immer der **Durchschnitt aller Einbrüche** und die wichtigsten Gründe
  **dafür/dagegen**.
- Die KI-Recherche ordnet zusätzlich den **Auslöser** ein (Gesamtmarkt, einmalig, grundlegend).
  Das kann die Statistik nicht wissen, ist aber oft entscheidend.

Einschränkung: Die Watchlist enthält nur heutige Indexmitglieder. Firmen, die nach einem
Absturz aus dem Index geflogen sind, fehlen in den Daten, dadurch fallen die Quoten etwas zu
optimistisch aus.

## Installation auf dem Raspberry Pi

Getestet für Raspberry Pi OS **Bookworm** (Python 3.11+). Ein Pi 3B+ reicht, ein Pi 4/5 ist angenehmer.

```bash
git clone <dieses-repo>
cd <repo>/boersen-bot
./installieren.sh
```

Das Skript installiert alles in einen eigenen Ordner (`venv`), legt `config.toml` an und richtet
einen Dienst ein, der beim Booten automatisch startet. Am Ende zeigt es die Adresse, z. B.
`http://192.168.1.50:8080` – im Browser am PC oder Handy öffnen.

Der erste Durchlauf dauert einige Minuten (55 Aktien × mehrere Quellen). Danach lädt der Bot
einmalig 15 Jahre Kurse für das Rebound-Modell. Das dauert noch einmal ein paar Minuten.

### Einstellungen (`config.toml`)

```toml
[ki]
anthropic_api_key = "sk-ant-..."     # für die KI-Begründung

[benachrichtigung]
ntfy_thema = "mein-boersenbot-x7k2"  # Push aufs Handy, Name frei wählbar (schwer erratbar!)

[quellen]
sec_user_agent = "MeinBoersenbot deine@mail.de"  # schaltet SEC EDGAR frei
finnhub_key = ""                                 # optional
```

Danach: `sudo systemctl restart boersenbot`

- **Claude-API-Key:** auf [console.anthropic.com](https://console.anthropic.com) anlegen.
  Die KI recherchiert nur bei starken Trends, höchstens einmal pro Aktie und Tag –
  realistisch ein paar Cent bis wenige Euro im Monat. Mit `auto_analyse = false` nur per Knopfdruck.
- **Push (ntfy):** App „ntfy“ installieren, das Thema abonnieren, denselben Namen in die Config schreiben.
  Mit `web_adresse = "http://192.168.1.50:8080"` öffnet ein Tipp auf die Nachricht direkt die Aktie.

### Nützliche Befehle

```bash
journalctl -u boersenbot -f        # Log live ansehen
sudo systemctl restart boersenbot  # nach Änderungen an config.toml
sudo systemctl stop boersenbot     # anhalten
```

## Schnittstelle für ein ESP32-Display

`GET /api/scores?stark=1` liefert die starken Trends als JSON – damit kann z. B. das
SmallTV-Display aus diesem Repo die aktuellen Alarme anzeigen:

```json
{"schwelle": 65, "aktien": [{"symbol": "RHM.DE", "name": "Rheinmetall", "score": 90,
  "richtung": 1, "kurs": 169.03, "chg_1d": 0.084, "chg_20d": 0.366, "flags": ["Volumen ×3.9"]}]}
```

`GET /api/scores` liefert alle Aktien, `GET /api/status` den Laufstatus.

## Lokal ausprobieren (ohne Pi)

```bash
cd boersen-bot
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt pytest
./venv/bin/python -m pytest tests     # Tests mit simulierten Daten, ohne Internet
cp config.example.toml config.toml
./venv/bin/python start.py            # → http://localhost:8080
```

## Grenzen – ehrlich gesagt

- Kostenlose Kurse sind **15–20 Min. verzögert** und nur als Tageskerzen genutzt. Für Trends über
  Tage und Wochen reicht das völlig, für schnelles Trading nicht.
- `yfinance` ist eine inoffizielle Schnittstelle. Wenn Yahoo etwas ändert, hilft meist
  `./venv/bin/pip install -U yfinance`.
- Der Score ist eine Regel-Sammlung, keine Vorhersage. Er zeigt, **dass** sich etwas Ungewöhnliches
  tut – nicht, ob es weitergeht.
- Die Stimmungsbewertung der Schlagzeilen ist bewusst simpel (Wortlisten), damit sie auf dem Pi
  schnell läuft. Die eigentliche Einordnung macht die KI.
- **Keine Anlageberatung.**

## Aufbau

```
boersen-bot/
├── start.py              Startpunkt (Sammler + Webserver)
├── installieren.sh       Einrichtung auf dem Pi inkl. systemd-Dienst
├── config.example.toml   Vorlage für config.toml
├── boersenbot/
│   ├── quellen.py        alle Datenquellen
│   ├── scoring.py        Score-Berechnung
│   ├── rebound.py        Rebound-Chance (Training + Bewertung)
│   ├── stimmung.py       Stimmung von Schlagzeilen
│   ├── analyse.py        KI-Recherche (Claude + Websuche)
│   ├── bot.py            Ablauf, Zeitplan, Meldungen
│   ├── melden.py         Push über ntfy
│   ├── db.py             SQLite-Speicher
│   ├── web.py            Weboberfläche + JSON-API
│   └── templates/, static/
└── tests/                Tests mit simulierten Daten
```
