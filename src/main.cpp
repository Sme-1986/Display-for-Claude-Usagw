// Claude + Solar Display fuer GeekMagic SmallTV (240x240 ST7789)
// Alle Werte kommen aus Home Assistant (ein Request auf /api/template).
// Einrichtung ueber die Weboberflaeche des Geraets, nichts ist einkompiliert.

#include <Arduino.h>
#include <LittleFS.h>
#include <TFT_eSPI.h>
#include <WiFiManager.h>
#include <time.h>

#if defined(ESP8266)
  #include <ESP8266WiFi.h>
  #include <ESP8266WebServer.h>
  #include <ESP8266HTTPClient.h>
  #include <ESP8266HTTPUpdateServer.h>
  #include <WiFiClientSecureBearSSL.h>
  typedef ESP8266WebServer WebSrv;
  typedef ESP8266HTTPUpdateServer UpdateSrv;
#else
  #include <WiFi.h>
  #include <WebServer.h>
  #include <HTTPClient.h>
  #include <HTTPUpdateServer.h>
  #include <WiFiClientSecure.h>
  typedef WebServer WebSrv;
  typedef HTTPUpdateServer UpdateSrv;
#endif

#define FW_VERSION "1.0.0"

TFT_eSPI tft;
WebSrv server(80);
UpdateSrv updater;

// ---------------------------------------------------------------- Konfiguration

struct Field {
  const char *key;
  const char *label;
  const char *hint;
  String value;
};

enum {
  F_URL, F_TOKEN,
  F_CL5H, F_CL7D,
  F_PV1, F_PV1N, F_PV2, F_PV2N, F_PV3, F_PV3N, F_PVMAX,
  F_SOC, F_BATPWR, F_BATINV,
  F_ETOTAL, F_ETODAY,
  F_SECS, F_BRIGHT, F_TZ,
  F_COUNT
};

Field cfg[F_COUNT] = {
  {"ha_url",   "Home Assistant URL", "z.B. http://192.168.1.10:8123", ""},
  {"ha_token", "Long-Lived Access Token", "leer lassen = unveraendert", ""},
  {"cl_5h",    "Claude Session (5h) Entity", "", "sensor.claude_session_usage"},
  {"cl_7d",    "Claude Woche Entity", "", "sensor.claude_weekly_usage"},
  {"pv1",      "Solar Array 1 Entity (Leistung)", "z.B. sensor.pv1_power", ""},
  {"pv1n",     "Array 1 Name", "", "Array 1"},
  {"pv2",      "Solar Array 2 Entity", "", ""},
  {"pv2n",     "Array 2 Name", "", "Array 2"},
  {"pv3",      "Solar Array 3 Entity", "", ""},
  {"pv3n",     "Array 3 Name", "", "Array 3"},
  {"pv_max",   "Max. Leistung pro Array in W", "0 = Balken automatisch skalieren", "0"},
  {"bat_soc",  "Batterie Ladestand Entity (%)", "", ""},
  {"bat_pwr",  "Batterie Leistung Entity (optional)", "positiv = laden", ""},
  {"bat_inv",  "Batterie-Leistung umkehren", "1 = positiv bedeutet entladen", "0"},
  {"e_total",  "Erzeugte Energie gesamt Entity", "", ""},
  {"e_today",  "Erzeugte Energie heute Entity (optional)", "", ""},
  {"secs",     "Sekunden pro Seite", "", "5"},
  {"bright",   "Helligkeit (5-100 %)", "", "80"},
  {"tz",       "Zeitzone (POSIX)", "", "CET-1CEST,M3.5.0,M10.5.0/3"},
};

void loadConfig() {
  File f = LittleFS.open("/config.txt", "r");
  if (!f) return;
  while (f.available()) {
    String line = f.readStringUntil('\n');
    line.trim();
    int eq = line.indexOf('=');
    if (eq < 1) continue;
    String k = line.substring(0, eq);
    for (auto &fd : cfg)
      if (k == fd.key) fd.value = line.substring(eq + 1);
  }
  f.close();
}

void saveConfig() {
  File f = LittleFS.open("/config.txt", "w");
  if (!f) return;
  for (auto &fd : cfg) {
    f.print(fd.key);
    f.print('=');
    f.println(fd.value);
  }
  f.close();
}

// ---------------------------------------------------------------- Daten

struct Reading {
  bool ok = false;
  float v = 0;
  String extra;  // Einheit bzw. resets_at
};

enum { R_PV1, R_PV2, R_PV3, R_SOC, R_BATPWR, R_ETOTAL, R_ETODAY, R_CL5H, R_CL7D, R_COUNT };
const uint8_t readingField[R_COUNT] = {F_PV1, F_PV2, F_PV3, F_SOC, F_BATPWR, F_ETOTAL, F_ETODAY, F_CL5H, F_CL7D};

Reading rd[R_COUNT];
String lastError = "noch keine Abfrage";
unsigned long lastFetch = 0, lastOk = 0;
bool everOk = false;

bool validEntity(const String &e) {
  if (e.length() < 3 || e.indexOf('.') < 1) return false;
  for (unsigned i = 0; i < e.length(); i++) {
    char c = e[i];
    if (!(isalnum((unsigned char)c) || c == '_' || c == '.')) return false;
  }
  return true;
}

bool haConfigured() { return cfg[F_URL].value.length() > 7 && cfg[F_TOKEN].value.length() > 10; }

bool isNumber(const String &s) {
  if (!s.length()) return false;
  char c = s[0];
  if (isdigit((unsigned char)c)) return true;
  return (c == '-' || c == '.') && s.length() > 1 && isdigit((unsigned char)s[1]);
}

float toWatts(const Reading &r) {
  if (r.extra == "kW") return r.v * 1000.0f;
  if (r.extra == "MW") return r.v * 1e6f;
  return r.v;
}

float toKwh(const Reading &r) {
  if (r.extra == "Wh") return r.v / 1000.0f;
  if (r.extra == "MWh") return r.v * 1000.0f;
  return r.v;
}

void fetchData() {
  lastFetch = millis();
  if (!haConfigured() || WiFi.status() != WL_CONNECTED) return;

  // Ein Template liefert alle Werte: "wert;extra|wert;extra|..."
  String body = F("{\"template\":\"");
  for (int i = 0; i < R_COUNT; i++) {
    if (i) body += '|';
    const String &e = cfg[readingField[i]].value;
    if (!validEntity(e)) { body += F("-;-"); continue; }
    const char *attr = (i >= R_CL5H) ? "resets_at" : "unit_of_measurement";
    body += "{{states('" + e + "')}};{{state_attr('" + e + "','" + attr + "')}}";
  }
  body += F("\"}");

  String url = cfg[F_URL].value;
  while (url.endsWith("/")) url.remove(url.length() - 1);
  url += F("/api/template");

  HTTPClient http;
  WiFiClient plain;
  int code;
  String resp;
  http.setTimeout(6000);
  if (url.startsWith("https")) {
#if defined(ESP8266)
    BearSSL::WiFiClientSecure tls;
#else
    WiFiClientSecure tls;
#endif
    tls.setInsecure();
    http.begin(tls, url);
    http.addHeader(F("Authorization"), "Bearer " + cfg[F_TOKEN].value);
    http.addHeader(F("Content-Type"), F("application/json"));
    code = http.POST(body);
    if (code == 200) resp = http.getString();
    http.end();
  } else {
    http.begin(plain, url);
    http.addHeader(F("Authorization"), "Bearer " + cfg[F_TOKEN].value);
    http.addHeader(F("Content-Type"), F("application/json"));
    code = http.POST(body);
    if (code == 200) resp = http.getString();
    http.end();
  }

  if (code != 200) {
    if (code == 401) lastError = F("401 - Token ungueltig");
    else if (code == 403) lastError = F("403 - Token braucht Admin-Rechte");
    else if (code < 0) lastError = "HA nicht erreichbar (" + HTTPClient::errorToString(code) + ")";
    else lastError = "HTTP " + String(code);
    return;
  }

  int pos = 0;
  for (int i = 0; i < R_COUNT; i++) {
    int end = resp.indexOf('|', pos);
    String part = (end < 0) ? resp.substring(pos) : resp.substring(pos, end);
    pos = (end < 0) ? resp.length() : end + 1;
    int semi = part.indexOf(';');
    String val = (semi < 0) ? part : part.substring(0, semi);
    val.trim();
    rd[i].ok = isNumber(val);
    rd[i].v = val.toFloat();
    rd[i].extra = (semi < 0) ? "" : part.substring(semi + 1);
    rd[i].extra.trim();
  }
  lastError = "";
  lastOk = millis();
  everOk = true;
}

// ---------------------------------------------------------------- Zeichnen

#define C_BG     TFT_BLACK
#define C_TEXT   TFT_WHITE
#define C_DIM    0x8C71  // grau
#define C_TRACK  0x2124  // dunkelgrau
#define C_CLAUDE 0xDBAA  // Claude-Orange (#D97757)
#define C_SUN    0xFE60  // gelb
#define C_GREEN  0x2DCB
#define C_AMBER  0xFD20
#define C_RED    0xF165
#define C_BLUE   0x3D7F

enum Page { P_CL5H, P_CL7D, P_SOLAR, P_BATTERY, P_ENERGY, P_COUNT };

bool pageEnabled(int p) {
  switch (p) {
    case P_CL5H: return validEntity(cfg[F_CL5H].value);
    case P_CL7D: return validEntity(cfg[F_CL7D].value);
    case P_SOLAR: return validEntity(cfg[F_PV1].value) || validEntity(cfg[F_PV2].value) || validEntity(cfg[F_PV3].value);
    case P_BATTERY: return validEntity(cfg[F_SOC].value);
    case P_ENERGY: return validEntity(cfg[F_ETOTAL].value) || validEntity(cfg[F_ETODAY].value);
  }
  return false;
}

void text(const String &s, int x, int y, const GFXfont *font, uint16_t color, uint8_t datum = MC_DATUM) {
  tft.setFreeFont(font);
  tft.setTextColor(color, C_BG);
  tft.setTextDatum(datum);
  tft.drawString(s, x, y);
}

// 1234.5 -> "1.234,5" (deutsche Schreibweise)
String fmtNum(float v, int decimals) {
  bool neg = v < 0;
  if (neg) v = -v;
  float scale = decimals == 2 ? 100.0f : decimals == 1 ? 10.0f : 1.0f;
  unsigned long scaled = (unsigned long)(v * scale + 0.5f);
  unsigned long whole = scaled / (unsigned long)scale;
  unsigned long frac = scaled % (unsigned long)scale;
  String w = String(whole), out;
  for (unsigned i = 0; i < w.length(); i++) {
    if (i && (w.length() - i) % 3 == 0) out += '.';
    out += w[i];
  }
  if (decimals) {
    out += ',';
    if (decimals == 2 && frac < 10) out += '0';
    out += String(frac);
  }
  return neg ? "-" + out : out;
}

String fmtWatts(float w) {
  if (fabsf(w) >= 10000) return fmtNum(w / 1000.0f, 1) + " kW";
  return fmtNum(w, 0) + " W";
}

void header(const char *title, uint16_t color, int page) {
  tft.fillScreen(C_BG);
  tft.fillSmoothRoundRect(14, 12, 5, 16, 2, color, C_BG);
  text(title, 27, 20, &FreeSansBold9pt7b, C_TEXT, ML_DATUM);
  // HA-Verbindung gestoert: kleiner roter Punkt oben rechts
  if (lastError.length() && everOk) tft.fillSmoothCircle(222, 20, 4, C_RED, C_BG);

  // Seitenpunkte unten
  int n = 0, idx = 0;
  for (int p = 0; p < P_COUNT; p++) {
    if (!pageEnabled(p)) continue;
    if (p == page) idx = n;
    n++;
  }
  int x0 = 120 - (n - 1) * 7;
  for (int i = 0; i < n; i++)
    tft.fillSmoothCircle(x0 + i * 14, 231, i == idx ? 3 : 2, i == idx ? color : C_TRACK, C_BG);
}

time_t nowTs() {
  time_t t = time(nullptr);
  return t > 1600000000 ? t : 0;  // 0 = Uhr noch nicht gestellt
}

void drawClaude(int page, const char *title, const Reading &r, long windowSecs) {
  header(title, C_CLAUDE, page);
  const int cx = 120, cy = 116, ro = 80, ri = 66;
  tft.drawSmoothArc(cx, cy, ro, ri, 30, 330, C_TRACK, C_BG, true);

  if (!r.ok) {
    text("--", cx, cy - 4, &FreeSansBold24pt7b, C_DIM);
    text("keine Daten", cx, 210, &FreeSans9pt7b, C_DIM);
    return;
  }

  float pct = constrain(r.v, 0.0f, 100.0f);
  time_t now = nowTs();
  long resets = isNumber(r.extra) ? (long)r.extra.toInt() : 0;
  long left = (now && resets) ? resets - (long)now : 0;
  bool expired = now && resets && left <= 0;
  if (expired) pct = 0;  // Fenster ist abgelaufen, Limit wieder frei

  uint16_t col = pct >= 90 ? C_RED : pct >= 75 ? C_AMBER : C_CLAUDE;
  if (pct >= 1) tft.drawSmoothArc(cx, cy, ro, ri, 30, 30 + (int)(pct * 3.0f), col, C_BG, true);

  // Zeitmarke: wie viel vom Zeitfenster schon vorbei ist
  if (left > 0 && left <= windowSecs) {
    float a = (30.0f + 300.0f * (1.0f - (float)left / windowSecs)) * DEG_TO_RAD;
    int mx = cx - (int)roundf(sinf(a) * 73), my = cy + (int)roundf(cosf(a) * 73);
    tft.fillSmoothCircle(mx, my, 5, C_BG, C_BG);
    tft.fillSmoothCircle(mx, my, 3, C_TEXT, C_BG);
  }

  text(String((int)(pct + 0.5f)) + "%", cx + 3, cy - 6, &FreeSansBold24pt7b, C_TEXT);
  text("genutzt", cx, cy + 30, &FreeSans9pt7b, C_DIM);

  String foot;
  if (expired) foot = "Limit wieder frei";
  else if (left <= 0) foot = "";
  else if (left < 86400) {
    foot = "Reset in ";
    if (left >= 3600) foot += String(left / 3600) + "h ";
    foot += String((left % 3600) / 60) + "m";
  } else {
    static const char *days[] = {"So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"};
    time_t rt = resets;
    struct tm *tmv = localtime(&rt);
    char buf[24];
    snprintf(buf, sizeof(buf), "Reset %s %02d:%02d", days[tmv->tm_wday], tmv->tm_hour, tmv->tm_min);
    foot = buf;
  }
  text(foot, cx, 210, &FreeSans9pt7b, C_DIM);
}

void drawSolar() {
  header("SOLAR", C_SUN, P_SOLAR);
  const uint8_t ids[3] = {R_PV1, R_PV2, R_PV3};
  const uint8_t names[3] = {F_PV1N, F_PV2N, F_PV3N};
  float w[3], total = 0, peak = 0;
  bool any = false;
  for (int i = 0; i < 3; i++) {
    w[i] = rd[ids[i]].ok ? max(0.0f, toWatts(rd[ids[i]])) : 0;
    any |= rd[ids[i]].ok;
    total += w[i];
    peak = max(peak, w[i]);
  }
  float scale = cfg[F_PVMAX].value.toFloat();
  if (scale <= 0) scale = max(peak, 50.0f);

  text(any ? fmtWatts(total) : String("--"), 120, 66, &FreeSansBold24pt7b, any ? C_TEXT : C_DIM);

  for (int i = 0; i < 3; i++) {
    int y = 106 + i * 38;
    bool ok = rd[ids[i]].ok;
    text(cfg[names[i]].value, 14, y, &FreeSans9pt7b, C_DIM, ML_DATUM);
    text(ok ? fmtWatts(w[i]) : String("--"), 226, y, &FreeSansBold9pt7b, ok ? C_TEXT : C_DIM, MR_DATUM);
    tft.fillSmoothRoundRect(14, y + 13, 212, 8, 4, C_TRACK, C_BG);
    int bw = (int)(212.0f * min(1.0f, w[i] / scale));
    if (bw >= 8) tft.fillSmoothRoundRect(14, y + 13, bw, 8, 4, C_SUN, C_TRACK);
  }
}

void drawBattery() {
  header("BATTERIE", C_GREEN, P_BATTERY);
  const Reading &r = rd[R_SOC];
  const int x = 45, y = 46, w = 140, h = 66;
  tft.fillSmoothRoundRect(x, y, w, h, 12, C_TEXT, C_BG);
  tft.fillSmoothRoundRect(x + 4, y + 4, w - 8, h - 8, 8, C_BG, C_TEXT);
  tft.fillSmoothRoundRect(x + w + 3, y + 20, 7, h - 40, 3, C_TEXT, C_BG);

  if (!r.ok) {
    text("--", 120, 152, &FreeSansBold24pt7b, C_DIM);
    text("keine Daten", 120, 200, &FreeSans9pt7b, C_DIM);
    return;
  }
  float soc = constrain(r.v, 0.0f, 100.0f);
  uint16_t col = soc < 20 ? C_RED : soc < 50 ? C_AMBER : C_GREEN;
  int fw = (int)((w - 16) * soc / 100.0f);
  if (fw >= 8) tft.fillSmoothRoundRect(x + 8, y + 8, fw, h - 16, 5, col, C_BG);

  text(String((int)(soc + 0.5f)) + "%", 123, 152, &FreeSansBold24pt7b, C_TEXT);

  if (rd[R_BATPWR].ok) {
    float p = toWatts(rd[R_BATPWR]);
    if (cfg[F_BATINV].value == "1") p = -p;
    if (fabsf(p) < 10) text("Standby", 120, 200, &FreeSans9pt7b, C_DIM);
    else if (p > 0) text("Laden  " + fmtWatts(p), 120, 200, &FreeSansBold9pt7b, C_GREEN);
    else text("Entladen  " + fmtWatts(-p), 120, 200, &FreeSansBold9pt7b, C_AMBER);
  }
}

void drawEnergy() {
  header("ERTRAG", C_BLUE, P_ENERGY);
  bool hasToday = validEntity(cfg[F_ETODAY].value);
  bool hasTotal = validEntity(cfg[F_ETOTAL].value);
  int yT = (hasToday && hasTotal) ? 50 : 88;

  if (hasTotal) {
    text("Gesamt", 120, yT, &FreeSans9pt7b, C_DIM);
    if (rd[R_ETOTAL].ok) {
      float kwh = toKwh(rd[R_ETOTAL]);
      bool mwh = kwh >= 100000;
      text(mwh ? fmtNum(kwh / 1000.0f, 1) : fmtNum(kwh, kwh < 1000 ? 1 : 0), 120, yT + 38, &FreeSansBold24pt7b, C_TEXT);
      text(mwh ? "MWh" : "kWh", 120, yT + 72, &FreeSansBold9pt7b, C_BLUE);
    } else {
      text("--", 120, yT + 38, &FreeSansBold24pt7b, C_DIM);
    }
  }
  if (hasToday) {
    int y = hasTotal ? 150 : 88;
    if (hasTotal) tft.fillRect(60, y - 8, 120, 2, C_TRACK);
    text("Heute", 120, y + 14, &FreeSans9pt7b, C_DIM);
    text(rd[R_ETODAY].ok ? fmtNum(toKwh(rd[R_ETODAY]), 1) + " kWh" : String("--"), 120, y + 46,
         &FreeSansBold18pt7b, rd[R_ETODAY].ok ? C_TEXT : C_DIM);
  }
}

void drawMessage(const char *title, const String &l1, const String &l2 = "", const String &l3 = "") {
  tft.fillScreen(C_BG);
  tft.fillSmoothRoundRect(14, 12, 5, 16, 2, C_CLAUDE, C_BG);
  text(title, 27, 20, &FreeSansBold9pt7b, C_TEXT, ML_DATUM);
  text(l1, 120, 90, &FreeSans9pt7b, C_TEXT);
  text(l2, 120, 125, &FreeSansBold9pt7b, C_CLAUDE);
  text(l3, 120, 160, &FreeSans9pt7b, C_DIM);
}

void drawPage(int p) {
  switch (p) {
    case P_CL5H: drawClaude(p, "CLAUDE  SESSION", rd[R_CL5H], 5L * 3600); break;
    case P_CL7D: drawClaude(p, "CLAUDE  WOCHE", rd[R_CL7D], 7L * 86400); break;
    case P_SOLAR: drawSolar(); break;
    case P_BATTERY: drawBattery(); break;
    case P_ENERGY: drawEnergy(); break;
  }
}

void setBacklight() {
  int b = constrain(cfg[F_BRIGHT].value.toInt(), 5, 100) * 255 / 100;
#if BL_INVERTED
  b = 255 - b;
#endif
  analogWrite(BL_PIN, b);
}

// ---------------------------------------------------------------- Weboberflaeche

String esc(const String &s) {
  String o = s;
  o.replace("&", "&amp;");
  o.replace("\"", "&quot;");
  o.replace("<", "&lt;");
  return o;
}

const char PAGE_HEAD[] PROGMEM = R"(<!doctype html><html lang=de><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Claude Display</title>
<style>body{font:16px system-ui,sans-serif;background:#141413;color:#eee;max-width:520px;margin:0 auto;padding:16px}
h1{color:#d97757;font-size:22px}h2{font-size:15px;color:#d97757;margin:26px 0 4px;text-transform:uppercase;letter-spacing:.05em}
label{display:block;margin-top:12px;font-size:14px}small{color:#999}
input{width:100%;box-sizing:border-box;padding:9px;margin-top:4px;border:1px solid #444;border-radius:6px;background:#222;color:#eee;font-size:15px}
button{margin-top:24px;width:100%;padding:12px;border:0;border-radius:6px;background:#d97757;color:#fff;font-size:16px;font-weight:600}
.s{padding:10px;border-radius:6px;background:#222;font-size:14px}a{color:#d97757}</style>
<h1>Claude Display</h1>)";

void handleRoot() {
  server.setContentLength(CONTENT_LENGTH_UNKNOWN);
  server.send(200, "text/html; charset=utf-8", "");
  server.sendContent_P(PAGE_HEAD);

  String s = F("<div class=s>Home Assistant: ");
  if (!haConfigured()) s += F("noch nicht eingerichtet");
  else if (lastError.length()) s += "<b style='color:#f66'>" + esc(lastError) + "</b>";
  else s += F("<b style='color:#6c6'>verbunden</b>");
  if (everOk) {
    s += F("<br><small>");
    for (int i = 0; i < R_COUNT; i++) {
      const String &e = cfg[readingField[i]].value;
      if (!validEntity(e)) continue;
      s += esc(e) + " = " + (rd[i].ok ? String(rd[i].v) : String("?")) + "<br>";
    }
    s += F("</small>");
  }
  s += F("</div><form method=post action=/save>");
  server.sendContent(s);

  for (int i = 0; i < F_COUNT; i++) {
    s = "";
    if (i == F_URL) s += F("<h2>Home Assistant</h2>");
    if (i == F_CL5H) s += F("<h2>Claude</h2>");
    if (i == F_PV1) s += F("<h2>Solar</h2>");
    if (i == F_SOC) s += F("<h2>Batterie</h2>");
    if (i == F_ETOTAL) s += F("<h2>Ertrag</h2>");
    if (i == F_SECS) s += F("<h2>Anzeige</h2>");
    s += "<label>" + String(cfg[i].label);
    if (cfg[i].hint[0]) s += " <small>(" + String(cfg[i].hint) + ")</small>";
    s += "<input name=" + String(cfg[i].key);
    if (i == F_TOKEN) s += F(" type=password autocomplete=off");
    else s += " value=\"" + esc(cfg[i].value) + "\"";
    s += F("></label>");
    server.sendContent(s);
  }
  server.sendContent(F("<button>Speichern</button></form><p><small>Firmware " FW_VERSION
                       " &middot; <a href=/update>Firmware-Update</a> &middot; <a href=/wifireset "
                       "onclick=\"return confirm('WLAN-Daten wirklich loeschen?')\">WLAN zuruecksetzen</a></small></p>"));
  server.sendContent("");
}

void handleSave() {
  for (int i = 0; i < F_COUNT; i++) {
    if (!server.hasArg(cfg[i].key)) continue;
    String v = server.arg(cfg[i].key);
    v.trim();
    v.replace("\n", "");
    v.replace("\r", "");
    if (i == F_TOKEN && !v.length()) continue;  // leer = Token behalten
    cfg[i].value = v;
  }
  saveConfig();
  setBacklight();
  configTzTime(cfg[F_TZ].value.c_str(), "pool.ntp.org", "time.nist.gov");
  lastFetch = 0;  // sofort neu abfragen
  server.sendHeader("Location", "/");
  server.send(303, "text/plain", "");
}

// ---------------------------------------------------------------- Setup / Loop

int curPage = -1;
unsigned long pageShown = 0;
bool infoShown = false;

void setup() {
  Serial.begin(115200);
  pinMode(BL_PIN, OUTPUT);
  LittleFS.begin();
  loadConfig();

  tft.init();
  tft.setRotation(0);
  tft.fillScreen(C_BG);
  setBacklight();
  drawMessage("CLAUDE DISPLAY", "Verbinde mit WLAN ...");

  WiFi.mode(WIFI_STA);
  WiFiManager wm;
  wm.setDebugOutput(false);
  wm.setConfigPortalTimeout(300);
  wm.setAPCallback([](WiFiManager *) {
    drawMessage("WLAN EINRICHTEN", "Mit diesem WLAN verbinden:", "Claude-Display", "dann 192.168.4.1 oeffnen");
  });
  if (!wm.autoConnect("Claude-Display")) ESP.restart();

  configTzTime(cfg[F_TZ].value.c_str(), "pool.ntp.org", "time.nist.gov");

  server.on("/", HTTP_GET, handleRoot);
  server.on("/save", HTTP_POST, handleSave);
  server.on("/wifireset", HTTP_GET, []() {
    server.send(200, "text/plain", "WLAN-Daten geloescht, Geraet startet neu.");
    delay(500);
    WiFiManager w;
    w.resetSettings();
    ESP.restart();
  });
  updater.setup(&server);  // Firmware-Update unter /update
  server.begin();

  drawMessage("VERBUNDEN", "Einrichtung im Browser:", WiFi.localIP().toString(), WiFi.SSID());
  pageShown = millis();
}

void loop() {
  server.handleClient();
  unsigned long nowMs = millis();

  // Startinfo (IP-Adresse) 8 Sekunden stehen lassen
  if (!infoShown) {
    if (nowMs - pageShown < 8000) return;
    infoShown = true;
    fetchData();
    pageShown = 0;
  }

  unsigned long interval = (unsigned long)constrain(cfg[F_SECS].value.toInt(), 2, 120) * 1000UL;
  if (pageShown && nowMs - pageShown < interval) return;

  // Daten direkt vor dem Seitenwechsel holen, damit nichts sichtbar haengt
  if (!lastFetch || nowMs - lastFetch > 30000) fetchData();
  pageShown = millis();

  if (!haConfigured()) {
    drawMessage("EINRICHTUNG", "Im Browser oeffnen:", WiFi.localIP().toString(), "HA-URL und Token eintragen");
    return;
  }
  if (lastError.length() && (!everOk || millis() - lastOk > 300000UL)) {
    drawMessage("HOME ASSISTANT", "Keine Verbindung", WiFi.localIP().toString(), lastError.substring(0, 26));
    return;
  }

  for (int i = 0; i < P_COUNT; i++) {
    curPage = (curPage + 1) % P_COUNT;
    if (pageEnabled(curPage)) {
      drawPage(curPage);
      return;
    }
  }
  drawMessage("EINRICHTUNG", "Keine Entities gesetzt", WiFi.localIP().toString(), "im Browser eintragen");
}
