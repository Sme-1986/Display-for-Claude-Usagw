"""Startet Börsen-Bot: Hintergrund-Sammler + Weboberfläche."""
import logging

from waitress import serve

from boersenbot.bot import Bot
from boersenbot.config import lade
from boersenbot.web import erstelle_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("yfinance").setLevel(logging.WARNING)

cfg = lade()
bot = Bot(cfg)
bot.starten()
app = erstelle_app(bot)

if __name__ == "__main__":
    logging.info("Weboberfläche auf http://0.0.0.0:%s", cfg.port)
    serve(app, host="0.0.0.0", port=cfg.port, threads=4)
