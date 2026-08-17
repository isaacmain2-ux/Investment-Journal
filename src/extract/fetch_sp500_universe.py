"""
Generate config/universe_sp500.csv from Wikipedia's S&P 500 list.

Run occasionally (the index changes rarely), commit the CSV. Kept OUT of the daily
pipeline on purpose: the daily run reads the committed CSV, so a Wikipedia hiccup can
never break ingestion. Needs `lxml` for pandas.read_html.

    python -m src.extract.fetch_sp500_universe
"""
from __future__ import annotations

import csv

WIKI_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"


def _fetch_tables(url):
    """Fetch with a browser User-Agent (Wikipedia 403s the default urllib UA), then
    parse the returned HTML - not the URL - with pandas."""
    import io
    import pandas as pd
    import requests
    ua = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    resp = requests.get(url, headers={"User-Agent": ua}, timeout=30)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text))   # network seam


def to_constituents(df) -> list[dict]:
    """Map the Wikipedia table to tidy ticker/name/sector/cik rows. Pure."""
    import pandas as pd
    cols = {str(c).lower(): c for c in df.columns}

    def col(*names):
        return next((cols[n] for n in names if n in cols), None)

    sym, name = col("symbol", "ticker"), col("security", "company")
    sector, cik = col("gics sector", "sector"), col("cik")
    out = []
    for _, r in df.iterrows():
        t = str(r[sym]).strip().upper()
        if not t or t == "NAN":
            continue
        out.append({
            "ticker": t,
            "name": str(r[name]).strip() if name else "",
            "sector": str(r[sector]).strip() if sector else "",
            "cik": str(int(r[cik])).zfill(10) if cik and pd.notna(r[cik]) else "",
        })
    return out


def write_csv(rows, path="config/universe_sp500.csv") -> int:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "name", "sector", "cik"])
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def main():
    rows = to_constituents(_fetch_tables(WIKI_URL)[0])
    n = write_csv(rows)
    print(f"wrote {n} S&P 500 constituents to config/universe_sp500.csv")


if __name__ == "__main__":
    main()