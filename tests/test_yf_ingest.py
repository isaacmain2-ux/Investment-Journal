"""Test for src/extract/yf_ingest.py - mocks fetch and every storage effect."""
import pandas as pd

from src.extract import yf_ingest
from src.extract.yf_client import PriceResult


class DummyCon:
    def close(self):
        pass


def test_run_orchestrates_and_reports(monkeypatch):
    def fake_fetch(tickers, start="2010-01-01", batch_size=30):
        df = pd.DataFrame({
            "price_date": [pd.Timestamp("2024-01-02").date(), pd.Timestamp("2024-01-03").date()],
            "open": [1.0, 2.0], "high": [1.0, 2.0], "low": [1.0, 2.0],
            "close": [1.0, 2.0], "adj_close": [1.0, 2.0], "volume": [10, 20]})
        return {t: PriceResult(t, df=df, status="ok") for t in tickers}

    monkeypatch.setattr(yf_ingest, "fetch_prices", fake_fetch)
    monkeypatch.setattr(yf_ingest.load_fred, "get_connection", lambda *a, **k: DummyCon())
    monkeypatch.setattr(yf_ingest.load_yf, "ensure_schema", lambda con: None)
    monkeypatch.setattr(yf_ingest.load_yf, "upsert_dim", lambda con, s: None)
    monkeypatch.setattr(yf_ingest.load_yf, "load_prices", lambda con, tk, df: 0)
    monkeypatch.setattr(yf_ingest.load_yf, "record_status", lambda *a, **k: None)
    monkeypatch.setattr(yf_ingest.load_yf, "save_raw_parquet", lambda *a, **k: None)

    cap = {}
    monkeypatch.setattr(yf_ingest, "write_report",
                        lambda md, path: cap.update(md=md, path=path) or path)

    rc = yf_ingest.run(only=["AAPL", "^GSPC"])
    assert rc == 0
    assert "Equity Ingestion Run" in cap["md"]
    assert "**Result: PASS**" in cap["md"]
    assert "`AAPL`" in cap["md"] and "`^GSPC`" in cap["md"]
