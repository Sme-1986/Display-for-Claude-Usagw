"""Start-Watchlist: DAX 40 + große US-Werte. In der Oberfläche änderbar."""

DAX = "^GDAXI"
SP500 = "^GSPC"

DAX40 = {
    "ADS.DE": "Adidas", "AIR.DE": "Airbus", "ALV.DE": "Allianz", "BAS.DE": "BASF",
    "BAYN.DE": "Bayer", "BEI.DE": "Beiersdorf", "BMW.DE": "BMW", "BNR.DE": "Brenntag",
    "CBK.DE": "Commerzbank", "CON.DE": "Continental", "1COV.DE": "Covestro",
    "DTG.DE": "Daimler Truck", "DBK.DE": "Deutsche Bank", "DB1.DE": "Deutsche Börse",
    "DHL.DE": "DHL Group", "DTE.DE": "Deutsche Telekom", "EOAN.DE": "E.ON",
    "FRE.DE": "Fresenius", "HNR1.DE": "Hannover Rück", "HEI.DE": "Heidelberg Materials",
    "HEN3.DE": "Henkel", "IFX.DE": "Infineon", "MBG.DE": "Mercedes-Benz",
    "MRK.DE": "Merck KGaA", "MTX.DE": "MTU Aero Engines", "MUV2.DE": "Münchener Rück",
    "P911.DE": "Porsche AG", "PAH3.DE": "Porsche SE", "QIA.DE": "Qiagen",
    "RHM.DE": "Rheinmetall", "RWE.DE": "RWE", "SAP.DE": "SAP", "SRT3.DE": "Sartorius",
    "SIE.DE": "Siemens", "ENR.DE": "Siemens Energy", "SHL.DE": "Siemens Healthineers",
    "SY1.DE": "Symrise", "VOW3.DE": "Volkswagen", "VNA.DE": "Vonovia", "ZAL.DE": "Zalando",
}

US = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia", "AMZN": "Amazon",
    "GOOGL": "Alphabet", "META": "Meta Platforms", "TSLA": "Tesla", "AVGO": "Broadcom",
    "AMD": "AMD", "NFLX": "Netflix", "PLTR": "Palantir", "JPM": "JPMorgan Chase",
    "LLY": "Eli Lilly", "COST": "Costco", "ORCL": "Oracle",
}


def benchmark_fuer(symbol: str) -> str:
    return DAX if symbol.upper().endswith((".DE", ".F")) else SP500


def eintraege() -> list[tuple[str, str, str]]:
    out = [(s, n, DAX) for s, n in DAX40.items()]
    out += [(s, n, SP500) for s, n in US.items()]
    return out
