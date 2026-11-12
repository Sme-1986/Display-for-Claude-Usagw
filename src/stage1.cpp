// Schritt 1: winzige Zwischen-Firmware fuer den SmallTV-Ultra.
// Die Original-Firmware hat zu wenig freien Speicher fuer die volle Firmware.
// Diese hier passt daneben und nimmt danach unter /update die volle Firmware an.

#include <Arduino.h>
#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <ESP8266HTTPUpdateServer.h>

ESP8266WebServer server(80);
ESP8266HTTPUpdateServer updater;

void setup() {
  // Gespeichertes WLAN der Original-Firmware weiterverwenden, zusaetzlich
  // immer ein eigenes WLAN oeffnen, falls das nicht klappt.
  WiFi.persistent(false);
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP("Claude-Display-Setup");
  WiFi.begin();

  server.on("/", []() {
    server.sendHeader("Location", "/update");
    server.send(302, "text/plain", "");
  });
  updater.setup(&server);
  server.begin();
}

void loop() { server.handleClient(); }
