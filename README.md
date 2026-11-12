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

Im Ordner [`firmware/`](firmware/) liegen die Dateien:

| Gerät | Chip | Datei |
|---|---|---|
| SmallTV / **SmallTV-Ultra** (häufigste Variante) | ESP8266 | `smalltv-ultra_schritt1_zwischenfirmware.bin`, danach `smalltv-ultra_schritt2_claude-display.bin` |
| **SmallTV-Pro** (mit Touch-Fläche oben) | ESP32 | `claude-display_smalltv-pro_esp32.bin` |

Welches Modell du hast, steht in der Weboberfläche der Original-Firmware
(Modellname / Firmware-Version, z. B. „Ultra-V9.0.x“) oder auf der Verpackung.

**Wichtig:** Die falsche Datei kann das Gerät unbrauchbar machen, bis man es öffnet und per
USB-Seriell-Adapter neu flasht. Im Zweifel erst das Modell klären. Die Original-Firmware
gibt es bei GeekMagic zum Download, falls du zurück möchtest.

## 2. Hochladen

### SmallTV-Ultra (zwei Schritte)

Die Original-Firmware lässt zu wenig Speicher frei, um die volle Firmware direkt anzunehmen
(„Not Enough Space“). Deshalb kommt zuerst eine winzige Zwischen-Firmware aufs Gerät.

1. `http://<IP-des-Displays>/update` öffnen und `smalltv-ultra_schritt1_zwischenfirmware.bin`
   hochladen. Das Gerät startet neu; der Bildschirm zeigt in diesem Zustand nichts Sinnvolles.
2. Etwa 30 Sekunden warten und dieselbe Adresse `http://<IP-des-Displays>/update` erneut öffnen.
   Ist das Gerät dort nicht erreichbar: mit dem offenen WLAN **Claude-Display-Setup** verbinden
   und `http://192.168.4.1/update` öffnen.
3. `smalltv-ultra_schritt2_claude-display.bin` hochladen. Nach dem Neustart zeigt das Display
   seine IP-Adresse. Erscheint stattdessen „WLAN einrichten“: mit dem WLAN **Claude-Display**
   verbinden, `192.168.4.1` öffnen, WLAN eintragen.

### SmallTV-Pro

Die `.bin` über `http://<IP-des-Displays>/update` hochladen; danach wie oben ab Schritt 3.

Spätere Updates gehen bei beiden Geräten direkt über `http://<IP>/update`.

## 3. Einrichten

Die IP-Adresse des Displays im Browser öffnen und eintragen:

- **Home Assistant URL**, z. B. `http://192.168.1.10:8123`
- **Long-Lived Access Token**: in Home Assistant unter *Profil → Sicherheit →
  Langlebige Zugangstoken* erstellen (Benutzer mit Admin-Rechten).
- **Entities** für die 3 Solar-Arrays, Batterie-Ladestand und Gesamtenergie.
  Die Entity-IDs findest du in Home Assistant unter *Einstellungen → Geräte & Dienste → Entitäten*.
  Einheiten (W/kW, Wh/kWh/MWh) werden automatisch erkannt.

Oben auf der Seite steht, ob die Verbindung klappt und welche Werte ankommen.

## 4. Claude-Limits nach Home Assistant bringen

### Weg 1 – HACS-Integration „Claude Usage“ (am einfachsten)

Die Community-Integration [trickv/hass-claude-usage](https://github.com/trickv/hass-claude-usage)
läuft komplett in Home Assistant, ein Skript auf dem Rechner ist dann nicht nötig.

1. [HACS](https://hacs.xyz) installieren, falls noch nicht vorhanden.
2. In HACS nach **Claude Usage** suchen, installieren, Home Assistant neu starten.
3. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Claude Usage*,
   dem angezeigten Link folgen, bei Claude anmelden und den Code einfügen.
4. In der Weboberfläche des Displays die vier Entities eintragen (die genauen IDs stehen
   in Home Assistant beim Gerät „Claude Usage“):

| Feld im Display | Sensor der Integration |
|---|---|
| Claude Session (5h) Entity | „Session Usage“ |
| Session Reset-Zeit Entity | „Session Reset Time“ |
| Claude Woche Entity | „Week Usage“ |
| Woche Reset-Zeit Entity | „Weekly Reset Time“ |

Die Integration ist inoffiziell und nutzt eine nicht dokumentierte Schnittstelle von Anthropic.
Das Abfrageintervall auf den voreingestellten 300 Sekunden lassen: Laut Autor sperrt Anthropic
die Abfrage bei zu häufigen Zugriffen für rund 24 Stunden.

### Weg 2 – Skript auf dem eigenen Rechner

[`tools/claude_usage_to_ha.py`](tools/claude_usage_to_ha.py) (nur Python 3, keine weiteren
Pakete) meldet die Limits an Home Assistant. Zugangsdaten in `~/.config/claude-display.json`:

```json
{"ha_url": "http://192.168.1.10:8123", "ha_token": "DEIN_TOKEN"}
```

Als Statuszeile von Claude Code in `~/.claude/settings.json` (nutzt nur dokumentierte Daten,
aktualisiert aber nur, während Claude Code läuft):

```json
{
  "statusLine": {
    "type": "command",
    "command": "python3 /pfad/zu/tools/claude_usage_to_ha.py --statusline"
  }
}
```

Oder dauerhaft im Hintergrund mit `python3 tools/claude_usage_to_ha.py --poll`
(gleiche nicht dokumentierte Schnittstelle wie Weg 1).

Das Skript legt `sensor.claude_session_usage` und `sensor.claude_weekly_usage` an – die
Voreinstellung im Display. Die Reset-Zeit-Felder bleiben dabei leer.

## Selbst bauen

```bash
pip install platformio
pio run                 # baut beide Varianten nach .pio/build/<env>/firmware.bin
```

Pin-Belegung und Display-Einstellungen stehen in [`platformio.ini`](platformio.ini).
