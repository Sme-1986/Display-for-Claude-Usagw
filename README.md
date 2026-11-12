# Claude- & Solar-Display

Firmware für den kleinen Display-Würfel **GeekMagic SmallTV** (240×240 Pixel).
Zeigt im 5-Sekunden-Wechsel:

| Seite | Inhalt |
|---|---|
| **Claude Session** | Verbrauch des 5-Stunden-Limits als Ring, Zeit bis zum Reset |
| **Claude Woche** | Verbrauch des Wochenlimits als Ring, Wochentag/Uhrzeit des Resets |
| **Solar** | Gesamtleistung groß, darunter die 3 Arrays einzeln mit Balken |
| **Batterie** | Ladestand als Batterie-Grafik, optional Laden/Entladen in Watt |
| **Ertrag** | Erzeugte Energie gesamt, optional „heute“ |

Der weiße Punkt auf dem Claude-Ring zeigt, wie viel vom Zeitfenster schon vorbei ist.
Liegt der farbige Bogen *vor* dem Punkt, verbrauchst du schneller, als das Limit nachwächst.
Ein Tageslimit gibt es bei Claude nicht – die beiden Fenster sind 5 Stunden und 7 Tage.

Alle Werte holt das Gerät aus Home Assistant. Seiten ohne eingetragene Entity werden übersprungen.

> **Stand:** Die Firmware kompiliert, wurde aber noch nicht auf echter Hardware getestet.

## 1. Die richtige BIN-Datei wählen

Im Ordner [`firmware/`](firmware/) liegen zwei Dateien:

| Gerät | Chip | Datei |
|---|---|---|
| SmallTV / **SmallTV-Ultra** (häufigste Variante) | ESP8266 | `claude-display_smalltv-ultra_esp8266.bin` |
| **SmallTV-Pro** (mit Touch-Fläche oben) | ESP32 | `claude-display_smalltv-pro_esp32.bin` |

Welches Modell du hast, steht in der Weboberfläche der Original-Firmware
(Modellname / Firmware-Version, z. B. „Ultra-V9.0.x“) oder auf der Verpackung.

**Wichtig:** Die falsche Datei kann das Gerät unbrauchbar machen, bis man es öffnet und per
USB-Seriell-Adapter neu flasht. Im Zweifel erst das Modell klären. Die Original-Firmware
gibt es bei GeekMagic zum Download, falls du zurück möchtest.

## 2. Hochladen

1. Das Display wie gewohnt ins WLAN bringen und seine IP-Adresse im Browser öffnen.
2. `http://<IP-des-Displays>/update` aufrufen (Firmware-Update der Original-Firmware).
3. Die passende `.bin` auswählen und hochladen. Das Gerät startet neu.
4. Normalerweise bleibt das WLAN gespeichert und das Display zeigt seine IP-Adresse an.
   Falls nicht: mit dem WLAN **Claude-Display** verbinden, `192.168.4.1` öffnen, WLAN eintragen.

Spätere Updates gehen genauso über `http://<IP>/update`.

## 3. Einrichten

Die IP-Adresse des Displays im Browser öffnen und eintragen:

- **Home Assistant URL**, z. B. `http://192.168.1.10:8123`
- **Long-Lived Access Token**: in Home Assistant unter *Profil → Sicherheit →
  Langlebige Zugangstoken* erstellen (Benutzer mit Admin-Rechten).
- **Entities** für die 3 Solar-Arrays, Batterie-Ladestand und Gesamtenergie.
  Die Entity-IDs findest du in Home Assistant unter *Einstellungen → Geräte & Dienste → Entitäten*.
  Einheiten (W/kW, Wh/kWh/MWh) werden automatisch erkannt.

Oben auf der Seite steht, ob die Verbindung klappt und welche Werte ankommen.

## 4. Claude-Limits an Home Assistant melden

Die Limits kennt nur dein Claude-Login, deshalb meldet sie ein kleines Skript auf deinem
Rechner an Home Assistant: [`tools/claude_usage_to_ha.py`](tools/claude_usage_to_ha.py)
(nur Python 3, keine weiteren Pakete).

Zugangsdaten für Home Assistant in `~/.config/claude-display.json` ablegen:

```json
{"ha_url": "http://192.168.1.10:8123", "ha_token": "DEIN_TOKEN"}
```

**Variante A – Statuszeile von Claude Code (empfohlen).** In `~/.claude/settings.json`:

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 /pfad/zu/tools/claude_usage_to_ha.py --statusline"
  }
}
```

Claude Code übergibt die Limits dann laufend an das Skript. Aktualisiert wird nur,
während Claude Code läuft.

**Variante B – Abfrage im Hintergrund.** `python3 tools/claude_usage_to_ha.py --poll`
fragt alle 3 Minuten ab, auch wenn du Claude nur im Browser oder in der App nutzt.
Das nutzt den Login von Claude Code und eine nicht dokumentierte Schnittstelle, die sich
jederzeit ändern kann.

Beide Varianten legen `sensor.claude_session_usage` und `sensor.claude_weekly_usage` an –
genau die Namen, die im Display voreingestellt sind.

## Selbst bauen

```bash
pip install platformio
pio run                 # baut beide Varianten nach .pio/build/<env>/firmware.bin
```

Pin-Belegung und Display-Einstellungen stehen in [`platformio.ini`](platformio.ini).
