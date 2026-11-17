"""Weboberfläche (Flask)."""
from __future__ import annotations

import re
import time
from datetime import datetime

from flask import Flask, abort, jsonify, redirect, render_template, request, url_for
from markupsafe import Markup, escape

from . import quellen
from .bot import Bot
from .watchlist_default import benchmark_fuer

_URL = re.compile(r"(https?://[^\s<>\"\)\]]+)")


def erstelle_app(bot: Bot) -> Flask:
    app = Flask(__name__)
    cfg, db = bot.cfg, bot.db

    # ------------------------------------------------------------ Filter
    @app.template_filter("zeit")
    def _zeit(ts):
        if not ts:
            return "–"
        d = datetime.fromtimestamp(ts)
        return d.strftime("%H:%M") if d.date() == datetime.now().date() else d.strftime("%d.%m. %H:%M")

    @app.template_filter("vor")
    def _vor(ts):
        if not ts:
            return "–"
        s = time.time() - ts
        if s < 0:
            s = -s
            return f"in {int(s // 60)} Min." if s < 3600 else f"in {s / 3600:.1f} Std."
        if s < 90:
            return "gerade eben"
        if s < 3600:
            return f"vor {int(s // 60)} Min."
        if s < 86400:
            return f"vor {int(s // 3600)} Std."
        return f"vor {int(s // 86400)} T."

    @app.template_filter("pct")
    def _pct(x, stellen=1):
        return "–" if x is None else f"{x * 100:+.{stellen}f} %".replace(".", ",")

    @app.template_filter("zahl")
    def _zahl(x, stellen=2):
        if x is None:
            return "–"
        return f"{x:,.{stellen}f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @app.template_filter("linkify")
    def _linkify(text):
        sicher = str(escape(text))
        return Markup(_URL.sub(r'<a href="\1" target="_blank" rel="noopener">\1</a>', sicher))

    @app.context_processor
    def _global():
        return {"cfg": cfg, "status": bot.status, "jetzt": time.time()}

    def stufe(score: int) -> str:
        if score >= cfg.schwelle_stark:
            return "stark"
        return "mittel" if score >= cfg.schwelle_stark * 0.65 else "gering"

    app.jinja_env.globals["stufe"] = stufe
    app.jinja_env.globals["linie"] = svg_linie

    # ------------------------------------------------------------ Seiten
    @app.get("/")
    def uebersicht():
        filt = request.args.get("filter", "stark")
        scores = db.aktuelle_scores()
        stark = [s for s in scores if s["score"] >= cfg.schwelle_stark and s["richtung"] != 0]
        if filt == "stark":
            liste = stark
        elif filt == "auf":
            liste = [s for s in scores if s["richtung"] > 0]
        elif filt == "ab":
            liste = [s for s in scores if s["richtung"] < 0]
        elif filt == "rebound":
            liste = sorted((s for s in scores if s["details"].get("rebound")),
                           key=lambda s: -s["details"]["rebound"]["chance"])
        else:
            filt, liste = "alle", scores
        heute = datetime.now().date().isoformat()
        return render_template(
            "index.html",
            liste=liste,
            filt=filt,
            anzahl={"alle": len(scores), "stark": len(stark),
                    "auf": sum(s["richtung"] > 0 for s in scores),
                    "ab": sum(s["richtung"] < 0 for s in scores),
                    "rebound": sum(bool(s["details"].get("rebound")) for s in scores)},
            mit_analyse=db.symbole_mit_analyse(heute),
            charts={s["symbol"]: db.cache_get(f"chart:{s['symbol']}", 10**9) or [] for s in liste},
        )

    @app.get("/aktie/<symbol>")
    def aktie(symbol):
        sc = db.letzter_score(symbol)
        if not sc:
            abort(404)
        return render_template(
            "aktie.html",
            s=sc,
            chart=db.cache_get(f"chart:{symbol}", 10**9) or [],
            verlauf=db.score_verlauf(symbol, 30),
            news=db.news(symbol, stunden=7 * 24, limit=80),
            analyse=db.analyse(symbol),
            analyse_laeuft=bot.analyse_laeuft(symbol),
        )

    @app.post("/aktie/<symbol>/analyse")
    def analyse_starten(symbol):
        if cfg.ki_aktiv:
            bot.analyse_im_hintergrund(symbol)
        return redirect(url_for("aktie", symbol=symbol))

    @app.post("/aktualisieren")
    def aktualisieren():
        bot.jetzt_aktualisieren()
        return redirect(request.referrer or url_for("uebersicht"))

    @app.route("/watchlist", methods=["GET", "POST"])
    def watchlist():
        fehler = None
        if request.method == "POST":
            if request.form.get("loeschen"):
                db.watch_del(request.form["loeschen"])
            else:
                symbol = request.form.get("symbol", "").strip().upper()
                if not re.fullmatch(r"[A-Z0-9.\-\^=]{1,15}", symbol):
                    fehler = "Ungültiges Kürzel. Beispiele: SAP.DE, AAPL, ASML.AS"
                else:
                    name = request.form.get("name", "").strip() or quellen.firmenname(symbol)
                    db.watch_add(symbol, name, benchmark_fuer(symbol))
                    bot.jetzt_aktualisieren()
                    return redirect(url_for("watchlist"))
        return render_template("watchlist.html", liste=db.watchlist(), fehler=fehler)

    @app.get("/status")
    def status():
        return render_template("status.html", laeufe=db.letzte_laeufe(15), modell=bot.rebound_modell())

    # ------------------------------------------------------------ API (z. B. für ein ESP32-Display)
    @app.get("/api/scores")
    def api_scores():
        nur_stark = request.args.get("stark") == "1"
        out = []
        for s in db.aktuelle_scores():
            if nur_stark and (s["score"] < cfg.schwelle_stark or s["richtung"] == 0):
                continue
            out.append({
                "symbol": s["symbol"], "name": s["name"], "score": s["score"],
                "richtung": s["richtung"], "kurs": s["kurs"],
                "chg_1d": s["chg_1d"], "chg_20d": s["chg_20d"],
                "flags": s["details"]["flags"], "ts": s["ts"],
                "rebound": (s["details"].get("rebound") or {}).get("chance"),
            })
        return jsonify({"schwelle": cfg.schwelle_stark, "aktien": out})

    @app.get("/api/status")
    def api_status():
        return jsonify(bot.status)

    return app


def svg_linie(punkte: list[float], breite: int = 120, hoehe: int = 32, rand: float = 2) -> Markup:
    """Kleiner Liniengraph als SVG-Pfad (ohne JavaScript-Bibliothek)."""
    werte = [p for p in punkte if p is not None]
    if len(werte) < 2:
        return Markup("")
    lo, hi = min(werte), max(werte)
    spanne = (hi - lo) or 1
    n = len(werte) - 1
    xy = [
        (rand + i * (breite - 2 * rand) / n, rand + (hi - v) * (hoehe - 2 * rand) / spanne)
        for i, v in enumerate(werte)
    ]
    d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in xy)
    flaeche = d + f" L{xy[-1][0]:.1f},{hoehe} L{xy[0][0]:.1f},{hoehe} Z"
    klasse = "pos" if werte[-1] >= werte[0] else "neg"
    return Markup(
        f'<svg class="linie {klasse}" viewBox="0 0 {breite} {hoehe}" preserveAspectRatio="none" '
        f'role="img" aria-label="Kursverlauf">'
        f'<path class="flaeche" d="{flaeche}"/><path class="strich" d="{d}"/></svg>'
    )
