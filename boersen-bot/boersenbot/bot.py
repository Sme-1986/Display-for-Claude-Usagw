"""Ablaufsteuerung: sammelt regelmäßig alle Quellen, berechnet Scores, meldet starke Trends."""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from . import analyse, melden, quellen, scoring
from .config import Config
from .db import DB
from .watchlist_default import eintraege

log = logging.getLogger(__name__)


class Bot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.db = DB(cfg.datenbank)
        if self.db.watchlist_leer():
            for s, n, b in eintraege():
                self.db.watch_add(s, n, b)
        self._wecker = threading.Event()
        self._lauf_lock = threading.Lock()
        self._analyse_laeuft: set[str] = set()
        self.status = {
            "laeuft": False,
            "fortschritt": "",
            "letzter_lauf": None,
            "naechster_lauf": None,
            "fehler": None,
            "quellen": {},
        }

    # ------------------------------------------------------------ Steuerung
    def starten(self) -> None:
        threading.Thread(target=self._schleife, daemon=True, name="boersenbot").start()

    def jetzt_aktualisieren(self) -> None:
        self._wecker.set()

    def _schleife(self) -> None:
        while True:
            self.lauf()
            pause = self.cfg.intervall_minuten * 60
            self.status["naechster_lauf"] = time.time() + pause
            self._wecker.wait(pause)
            self._wecker.clear()

    # ------------------------------------------------------------ Ein Durchlauf
    def lauf(self) -> None:
        if not self._lauf_lock.acquire(blocking=False):
            return
        start = time.time()
        self.status.update(laeuft=True, fehler=None, fortschritt="Kurse laden …")
        try:
            meldung = self._lauf()
            self.db.lauf_speichern(start, time.time() - start, "ok", meldung)
        except Exception as e:  # noqa: BLE001
            log.exception("Lauf fehlgeschlagen")
            self.status["fehler"] = str(e)
            self.db.lauf_speichern(start, time.time() - start, "fehler", str(e))
        finally:
            self.status.update(laeuft=False, fortschritt="", letzter_lauf=time.time())
            self._lauf_lock.release()

    def _lauf(self) -> str:
        cfg, db = self.cfg, self.db
        watch = db.watchlist()
        symbole = [w["symbol"] for w in watch]
        benchmarks = sorted({w["benchmark"] for w in watch})
        daten = quellen.kurse(symbole + benchmarks)
        zaehler: Counter = Counter()
        zaehler[quellen.Q_YAHOO_KURSE] = sum(1 for s in symbole if s in daten)

        social: dict = {}
        if cfg.apewisdom:
            self.status["fortschritt"] = "Reddit-Erwähnungen laden …"
            social = db.cache_get("apewisdom", 25 * 60) or quellen.apewisdom()
            db.cache_set("apewisdom", social)
            zaehler[quellen.Q_APE] = len(social)

        cik_tabelle: dict = {}
        if cfg.sec_user_agent:
            cik_tabelle = db.cache_get("sec_cik", 86400) or {}
            if not cik_tabelle:
                try:
                    cik_tabelle = quellen.sec_cik_tabelle(cfg.sec_user_agent)
                    db.cache_set("sec_cik", cik_tabelle)
                except Exception as e:  # noqa: BLE001
                    log.info("SEC-Tabelle: %s", e)

        # Nachrichten parallel holen (wenige Threads, um die Quellen nicht zu überlasten)
        def news_fuer(w) -> list[dict]:
            return self._news_sammeln(w["symbol"], w["name"], cik_tabelle)

        self.status["fortschritt"] = "Nachrichten sammeln …"
        with ThreadPoolExecutor(max_workers=4) as ex:
            for items in ex.map(news_fuer, watch):
                for it in items:
                    zaehler[it["quelle"]] += 1

        bewertet = 0
        for i, w in enumerate(watch, 1):
            s = w["symbol"]
            self.status["fortschritt"] = f"Bewerten {i}/{len(watch)}: {s}"
            if s not in daten:
                continue
            df = daten[s]
            termin = self._zahlen_termin(s)
            erg = scoring.berechne(
                df,
                bench=daten.get(w["benchmark"]),
                news=db.news(s, stunden=72),
                social=social.get(s.split(".")[0]) if quellen.ist_us(s) else None,
                zahlen_termin=termin,
            )
            db.score_speichern(s, erg.score, erg.richtung, erg.kurs, erg.chg_1d, erg.chg_20d, erg.details())
            verlauf = df["Close"].iloc[-130:]
            db.cache_set(f"chart:{s}", [[d.strftime("%Y-%m-%d"), round(float(v), 4)] for d, v in verlauf.items()])
            bewertet += 1

        self.status["quellen"] = dict(zaehler)
        db.alte_scores_loeschen()
        self._starke_melden()
        return f"{bewertet}/{len(watch)} Aktien bewertet"

    def _news_sammeln(self, symbol: str, name: str, cik_tabelle: dict) -> list[dict]:
        cfg, db = self.cfg, self.db
        key = f"news:{symbol}"
        if db.cache_get(key, cfg.news_cache_minuten * 60) is not None:
            return []
        items: list[dict] = []
        items += quellen.yahoo_news(symbol)
        items += quellen.yahoo_rss(symbol)
        items += quellen.google_news(symbol, name)
        if quellen.ist_us(symbol):
            items += quellen.finnhub_news(symbol, cfg.finnhub_key)
            items += quellen.sec_meldungen(symbol, cik_tabelle.get(symbol), cfg.sec_user_agent)
        db.news_speichern(items)
        db.cache_set(key, len(items))
        return items

    def _zahlen_termin(self, symbol: str) -> str | None:
        key = f"zahlen:{symbol}"
        wert = self.db.cache_get(key, 86400)
        if wert is None:
            wert = quellen.naechste_zahlen(symbol) or ""
            self.db.cache_set(key, wert)
        return wert or None

    # ------------------------------------------------------------ Melden + KI
    def _starke_melden(self) -> None:
        cfg, db = self.cfg, self.db
        tag = date.today().isoformat()
        for sc in db.aktuelle_scores():
            if sc["score"] < cfg.schwelle_stark or sc["richtung"] == 0:
                continue
            s = sc["symbol"]
            if db.schon_gemeldet(s, tag):
                continue
            db.als_gemeldet(s, tag)
            kurzfazit = ""
            if cfg.ki_aktiv and cfg.auto_analyse:
                self.status["fortschritt"] = f"KI recherchiert {s} …"
                text = self.analysieren(s)
                kurzfazit = _kurzfazit(text) if text else ""
            pfeil = "▲" if sc["richtung"] > 0 else "▼"
            melden.push(
                cfg,
                f"{pfeil} {sc['name']} – Score {sc['score']}",
                f"{sc['chg_1d']:+.1%} heute, {sc['chg_20d']:+.1%} in 20 Tagen. "
                + (", ".join(sc["details"]["flags"]) + ". " if sc["details"]["flags"] else "")
                + kurzfazit,
                f"{cfg.web_adresse.rstrip('/')}/aktie/{s}" if cfg.web_adresse else None,
            )

    def analysieren(self, symbol: str) -> str | None:
        """KI-Recherche für eine Aktie (synchron). Ergebnis landet in der DB."""
        if not self.cfg.ki_aktiv or symbol in self._analyse_laeuft:
            return None
        sc = self.db.letzter_score(symbol)
        if not sc:
            return None
        self._analyse_laeuft.add(symbol)
        try:
            text, q = analyse.recherchiere(self.cfg, symbol, sc["name"], sc, self.db.news(symbol, 72))
            self.db.analyse_speichern(symbol, date.today().isoformat(), sc["score"], self.cfg.modell, text, q)
            return text
        except Exception as e:  # noqa: BLE001
            log.exception("KI-Analyse %s", symbol)
            self.db.analyse_speichern(
                symbol, date.today().isoformat(), sc["score"], self.cfg.modell, f"Fehler bei der KI-Analyse: {e}", []
            )
            return None
        finally:
            self._analyse_laeuft.discard(symbol)

    def analyse_im_hintergrund(self, symbol: str) -> None:
        threading.Thread(target=self.analysieren, args=(symbol,), daemon=True).start()

    def analyse_laeuft(self, symbol: str) -> bool:
        return symbol in self._analyse_laeuft


def _kurzfazit(text: str) -> str:
    for zeile in text.splitlines():
        if zeile.lower().startswith("kurzfazit"):
            return zeile.split(":", 1)[-1].strip()
    return text.strip().splitlines()[0][:200] if text.strip() else ""
