"""SQLite-Speicher: Watchlist, Scores, News, KI-Analysen, Cache."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS watchlist (
    symbol    TEXT PRIMARY KEY,
    name      TEXT NOT NULL,
    benchmark TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    symbol     TEXT NOT NULL,
    ts         REAL NOT NULL,
    score      INTEGER NOT NULL,
    richtung   INTEGER NOT NULL,
    kurs       REAL,
    chg_1d     REAL,
    chg_20d    REAL,
    details    TEXT NOT NULL,
    PRIMARY KEY (symbol, ts)
);
CREATE TABLE IF NOT EXISTS news (
    id        TEXT PRIMARY KEY,
    symbol    TEXT NOT NULL,
    quelle    TEXT NOT NULL,
    titel     TEXT NOT NULL,
    url       TEXT,
    zeit      REAL NOT NULL,
    stimmung  REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS news_symbol_zeit ON news(symbol, zeit);
CREATE TABLE IF NOT EXISTS analysen (
    symbol  TEXT NOT NULL,
    tag     TEXT NOT NULL,
    ts      REAL NOT NULL,
    score   INTEGER,
    modell  TEXT,
    text    TEXT NOT NULL,
    quellen TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (symbol, tag)
);
CREATE TABLE IF NOT EXISTS cache (
    key  TEXT PRIMARY KEY,
    ts   REAL NOT NULL,
    wert TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS laeufe (
    ts      REAL PRIMARY KEY,
    dauer   REAL,
    status  TEXT,
    meldung TEXT
);
CREATE TABLE IF NOT EXISTS gemeldet (
    symbol TEXT NOT NULL,
    tag    TEXT NOT NULL,
    PRIMARY KEY (symbol, tag)
);
"""


class DB:
    def __init__(self, pfad: Path):
        pfad.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.con = sqlite3.connect(pfad, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.executescript(SCHEMA)

    def _exec(self, sql: str, args=()) -> sqlite3.Cursor:
        with self._lock:
            cur = self.con.execute(sql, args)
            self.con.commit()
            return cur

    def _all(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self._lock:
            return self.con.execute(sql, args).fetchall()

    def _one(self, sql: str, args=()):
        with self._lock:
            return self.con.execute(sql, args).fetchone()

    # --- Watchlist -------------------------------------------------------
    def watchlist(self) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM watchlist ORDER BY symbol")

    def watchlist_leer(self) -> bool:
        return self._one("SELECT COUNT(*) FROM watchlist")[0] == 0

    def watch_add(self, symbol: str, name: str, benchmark: str) -> None:
        self._exec(
            "INSERT OR REPLACE INTO watchlist VALUES (?,?,?)", (symbol.upper(), name, benchmark)
        )

    def watch_del(self, symbol: str) -> None:
        self._exec("DELETE FROM watchlist WHERE symbol=?", (symbol,))

    # --- Scores ----------------------------------------------------------
    def score_speichern(self, symbol, score, richtung, kurs, chg_1d, chg_20d, details: dict):
        self._exec(
            "INSERT OR REPLACE INTO scores VALUES (?,?,?,?,?,?,?,?)",
            (symbol, time.time(), score, richtung, kurs, chg_1d, chg_20d, json.dumps(details)),
        )

    def aktuelle_scores(self) -> list[dict]:
        rows = self._all(
            """SELECT s.*, w.name FROM scores s
               JOIN watchlist w ON w.symbol = s.symbol
               WHERE s.ts = (SELECT MAX(ts) FROM scores s2 WHERE s2.symbol = s.symbol)
               ORDER BY s.score DESC"""
        )
        return [_score_dict(r) for r in rows]

    def score_verlauf(self, symbol: str, tage: int = 30) -> list[dict]:
        rows = self._all(
            "SELECT ts, score, richtung FROM scores WHERE symbol=? AND ts>? ORDER BY ts",
            (symbol, time.time() - tage * 86400),
        )
        return [dict(r) for r in rows]

    def letzter_score(self, symbol: str) -> dict | None:
        r = self._one(
            """SELECT s.*, w.name FROM scores s JOIN watchlist w ON w.symbol=s.symbol
               WHERE s.symbol=? ORDER BY ts DESC LIMIT 1""",
            (symbol,),
        )
        return _score_dict(r) if r else None

    def alte_scores_loeschen(self, tage: int = 90) -> None:
        self._exec("DELETE FROM scores WHERE ts < ?", (time.time() - tage * 86400,))
        self._exec("DELETE FROM news WHERE zeit < ?", (time.time() - tage * 86400,))

    # --- News ------------------------------------------------------------
    def news_speichern(self, items: list[dict]) -> None:
        with self._lock:
            self.con.executemany(
                "INSERT OR IGNORE INTO news VALUES (:id,:symbol,:quelle,:titel,:url,:zeit,:stimmung)",
                items,
            )
            self.con.commit()

    def news(self, symbol: str, stunden: float = 72, limit: int = 60) -> list[dict]:
        rows = self._all(
            "SELECT * FROM news WHERE symbol=? AND zeit>? ORDER BY zeit DESC LIMIT ?",
            (symbol, time.time() - stunden * 3600, limit),
        )
        return [dict(r) for r in rows]

    # --- KI-Analysen -----------------------------------------------------
    def analyse_speichern(self, symbol, tag, score, modell, text, quellen: list[dict]):
        self._exec(
            "INSERT OR REPLACE INTO analysen VALUES (?,?,?,?,?,?,?)",
            (symbol, tag, time.time(), score, modell, text, json.dumps(quellen)),
        )

    def analyse(self, symbol: str, tag: str | None = None) -> dict | None:
        if tag:
            r = self._one("SELECT * FROM analysen WHERE symbol=? AND tag=?", (symbol, tag))
        else:
            r = self._one(
                "SELECT * FROM analysen WHERE symbol=? ORDER BY ts DESC LIMIT 1", (symbol,)
            )
        if not r:
            return None
        d = dict(r)
        d["quellen"] = json.loads(d["quellen"])
        return d

    def symbole_mit_analyse(self, tag: str) -> set[str]:
        return {r[0] for r in self._all("SELECT symbol FROM analysen WHERE tag=?", (tag,))}

    # --- Meldungen (nur 1x pro Tag) -------------------------------------
    def schon_gemeldet(self, symbol: str, tag: str) -> bool:
        return self._one("SELECT 1 FROM gemeldet WHERE symbol=? AND tag=?", (symbol, tag)) is not None

    def als_gemeldet(self, symbol: str, tag: str) -> None:
        self._exec("INSERT OR IGNORE INTO gemeldet VALUES (?,?)", (symbol, tag))

    # --- Cache -----------------------------------------------------------
    def cache_get(self, key: str, max_alter_s: float):
        r = self._one("SELECT ts, wert FROM cache WHERE key=?", (key,))
        if r and time.time() - r["ts"] < max_alter_s:
            return json.loads(r["wert"])
        return None

    def cache_set(self, key: str, wert) -> None:
        self._exec(
            "INSERT OR REPLACE INTO cache VALUES (?,?,?)", (key, time.time(), json.dumps(wert))
        )

    # --- Läufe -----------------------------------------------------------
    def lauf_speichern(self, start: float, dauer: float, status: str, meldung: str) -> None:
        self._exec("INSERT OR REPLACE INTO laeufe VALUES (?,?,?,?)", (start, dauer, status, meldung))
        self._exec("DELETE FROM laeufe WHERE ts < ?", (time.time() - 14 * 86400,))

    def letzte_laeufe(self, n: int = 10) -> list[dict]:
        return [dict(r) for r in self._all("SELECT * FROM laeufe ORDER BY ts DESC LIMIT ?", (n,))]


def _score_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["details"] = json.loads(d["details"])
    return d
