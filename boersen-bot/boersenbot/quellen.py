"""Alle kostenlosen Datenquellen.

Jede Funktion fängt ihre Fehler selbst ab und gibt im Fehlerfall eine leere Liste
zurück – fällt eine Quelle aus, läuft der Rest weiter.
"""
from __future__ import annotations

import calendar
import hashlib
import logging
import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import pandas as pd
import requests

from .stimmung import bewerte

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (X11; Linux aarch64) Boersenbot/1.0"
TIMEOUT = 15

# Namen der Quellen, wie sie in der Oberfläche erscheinen
Q_YAHOO_KURSE = "Yahoo Finance (Kurse)"
Q_YAHOO_NEWS = "Yahoo Finance"
Q_YAHOO_RSS = "Yahoo RSS"
Q_GOOGLE = "Google News"
Q_SEC = "SEC EDGAR"
Q_FINNHUB = "Finnhub"
Q_APE = "Reddit (ApeWisdom)"


def _get(url: str, **kw) -> requests.Response:
    headers = kw.pop("headers", {})
    headers.setdefault("User-Agent", UA)
    r = requests.get(url, headers=headers, timeout=TIMEOUT, **kw)
    r.raise_for_status()
    return r


def _item(symbol: str, quelle: str, titel: str, url: str | None, zeit: float) -> dict:
    titel = " ".join(titel.split())
    key = (url or titel).encode()
    return {
        "id": hashlib.sha1(symbol.encode() + key).hexdigest(),
        "symbol": symbol,
        "quelle": quelle,
        "titel": titel,
        "url": url,
        "zeit": zeit,
        "stimmung": bewerte(titel),
    }


def ist_us(symbol: str) -> bool:
    return "." not in symbol and not symbol.startswith("^")


# ---------------------------------------------------------------- Kurse
def kurse(symbole: list[str], zeitraum: str = "1y") -> dict[str, pd.DataFrame]:
    """Tageskerzen (OHLCV) für alle Symbole in einem Aufruf."""
    import yfinance as yf

    if not symbole:
        return {}
    df = yf.download(
        symbole,
        period=zeitraum,
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )
    out: dict[str, pd.DataFrame] = {}
    if df is None or df.empty:
        return out
    for s in symbole:
        try:
            if isinstance(df.columns, pd.MultiIndex):
                if s not in df.columns.get_level_values(0):
                    continue
                teil = df[s]
            else:
                teil = df
            teil = teil.dropna(subset=["Close"])
            if len(teil) >= 30:
                out[s] = teil[["Open", "High", "Low", "Close", "Volume"]].astype(float)
        except Exception as e:  # noqa: BLE001
            log.warning("Kurse %s: %s", s, e)
    return out


def firmenname(symbol: str) -> str:
    import yfinance as yf

    try:
        info = yf.Ticker(symbol).info
        return info.get("shortName") or info.get("longName") or symbol
    except Exception:  # noqa: BLE001
        return symbol


def naechste_zahlen(symbol: str) -> str | None:
    """Nächster/letzter Termin für Quartalszahlen (ISO-Datum) laut Yahoo."""
    import yfinance as yf

    try:
        cal = yf.Ticker(symbol).calendar
        daten = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if daten:
            d = daten[0]
            return d.isoformat() if hasattr(d, "isoformat") else str(d)
    except Exception as e:  # noqa: BLE001
        log.debug("Earnings %s: %s", symbol, e)
    return None


# ---------------------------------------------------------------- News
def yahoo_news(symbol: str) -> list[dict]:
    import yfinance as yf

    out = []
    try:
        for n in yf.Ticker(symbol).news or []:
            c = n.get("content", n)
            titel = c.get("title")
            if not titel:
                continue
            url = (c.get("canonicalUrl") or {}).get("url") or c.get("link")
            zeit = c.get("pubDate") or c.get("providerPublishTime")
            if isinstance(zeit, str):
                zeit = datetime.fromisoformat(zeit.replace("Z", "+00:00")).timestamp()
            out.append(_item(symbol, Q_YAHOO_NEWS, titel, url, float(zeit or time.time())))
    except Exception as e:  # noqa: BLE001
        log.info("Yahoo News %s: %s", symbol, e)
    return out


def _rss(symbol: str, quelle: str, url: str) -> list[dict]:
    out = []
    try:
        feed = feedparser.parse(_get(url).content)
        for e in feed.entries[:40]:
            t = e.get("published_parsed") or e.get("updated_parsed")
            zeit = calendar.timegm(t) if t else time.time()
            titel = e.get("title", "")
            if quelle == Q_GOOGLE and e.get("source", {}).get("title"):
                herkunft = e["source"]["title"]
                titel = titel.removesuffix(f" - {herkunft}") + f" ({herkunft})"
            out.append(_item(symbol, quelle, titel, e.get("link"), zeit))
    except Exception as e:  # noqa: BLE001
        log.info("%s %s: %s", quelle, symbol, e)
    return out


def yahoo_rss(symbol: str) -> list[dict]:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={quote_plus(symbol)}&region=US&lang=en-US"
    return _rss(symbol, Q_YAHOO_RSS, url)


def google_news(symbol: str, name: str) -> list[dict]:
    if ist_us(symbol):
        q, sprache = f'"{name}" stock when:3d', "hl=en-US&gl=US&ceid=US:en"
    else:
        q, sprache = f'"{name}" Aktie when:3d', "hl=de&gl=DE&ceid=DE:de"
    url = f"https://news.google.com/rss/search?q={quote_plus(q)}&{sprache}"
    return _rss(symbol, Q_GOOGLE, url)


def finnhub_news(symbol: str, key: str) -> list[dict]:
    if not key or not ist_us(symbol):
        return []
    heute = date.today()
    url = (
        "https://finnhub.io/api/v1/company-news"
        f"?symbol={symbol}&from={heute - timedelta(days=3)}&to={heute}&token={key}"
    )
    out = []
    try:
        for n in _get(url).json()[:40]:
            titel = n.get("headline")
            if titel:
                titel += f" ({n.get('source', 'Finnhub')})"
                out.append(_item(symbol, Q_FINNHUB, titel, n.get("url"), float(n.get("datetime", time.time()))))
    except Exception as e:  # noqa: BLE001
        log.info("Finnhub %s: %s", symbol, e)
    return out


# ---------------------------------------------------------------- SEC EDGAR
SEC_ITEMS = {
    "1.01": "Wichtiger Vertrag",
    "1.02": "Vertrag beendet",
    "2.01": "Übernahme/Verkauf abgeschlossen",
    "2.02": "Quartalszahlen",
    "2.05": "Restrukturierung",
    "2.06": "Abschreibung",
    "3.01": "Börsennotierung",
    "4.02": "Bilanzkorrektur",
    "5.02": "Wechsel im Management",
    "7.01": "Investoren-Info",
    "8.01": "Sonstiges Ereignis",
}


def sec_cik_tabelle(user_agent: str) -> dict[str, int]:
    r = _get("https://www.sec.gov/files/company_tickers.json", headers={"User-Agent": user_agent})
    return {v["ticker"].upper(): int(v["cik_str"]) for v in r.json().values()}


def sec_meldungen(symbol: str, cik: int | None, user_agent: str) -> list[dict]:
    """8-K-Pflichtmitteilungen der letzten 7 Tage."""
    if not cik or not user_agent:
        return []
    out = []
    try:
        r = _get(
            f"https://data.sec.gov/submissions/CIK{cik:010d}.json",
            headers={"User-Agent": user_agent},
        )
        rec = r.json()["filings"]["recent"]
        grenze = date.today() - timedelta(days=7)
        for form, tag, acc, doc, items in zip(
            rec["form"], rec["filingDate"], rec["accessionNumber"], rec["primaryDocument"], rec["items"]
        ):
            if form not in ("8-K", "8-K/A", "6-K"):
                continue
            d = date.fromisoformat(tag)
            if d < grenze:
                break
            beschr = ", ".join(SEC_ITEMS.get(i.strip(), i.strip()) for i in items.split(",") if i.strip())
            titel = f"{form}: {beschr or 'Pflichtmitteilung'}"
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc.replace('-', '')}/{doc}"
            zeit = datetime(d.year, d.month, d.day, 12, tzinfo=timezone.utc).timestamp()
            item = _item(symbol, Q_SEC, titel, url, zeit)
            item["stimmung"] = 0.0  # Formulare sind neutral, wichtig ist, DASS es eine gibt
            out.append(item)
    except Exception as e:  # noqa: BLE001
        log.info("SEC %s: %s", symbol, e)
    return out


# ---------------------------------------------------------------- Reddit
def apewisdom(seiten: int = 3) -> dict[str, dict]:
    """Erwähnungen auf Reddit (wallstreetbets, stocks, …) der letzten 24h."""
    out: dict[str, dict] = {}
    try:
        for seite in range(1, seiten + 1):
            data = _get(f"https://apewisdom.io/api/v1.0/filter/all-stocks/page/{seite}").json()
            for r in data.get("results", []):
                out[r["ticker"].upper()] = {
                    "rang": int(r.get("rank") or 0),
                    "rang_gestern": int(r.get("rank_24h_ago") or 0),
                    "erwaehnungen": int(r.get("mentions") or 0),
                    "erwaehnungen_gestern": int(r.get("mentions_24h_ago") or 0),
                }
            if seite >= int(data.get("pages", 1)):
                break
    except Exception as e:  # noqa: BLE001
        log.info("ApeWisdom: %s", e)
    return out
