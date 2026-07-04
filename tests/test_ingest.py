"""Test for src/extract/fred_ingest.py — mocks the network fetch and every
DB/raw side effect, so the orchestration logic is exercised offline."""
import pandas as pd

from src.extract import fred_ingest
from src.extract.fred_client import FetchResult


class DummyCon:
    def close(self):
        pass


def test_run_orchestrates_and_reports(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "testkey")

    def fake_fetch(sid, key, start="2005-01-01", retries=3):
        df = pd.DataFrame({
            "obs_date": [pd.Timestamp("2024-01-01").date(),
                         pd.Timestamp("2024-01-02").date()],
            "value": [1.0, 2.0],
        })
        return FetchResult(sid, df=df, status="ok")

    monkeypatch.setattr(fred_ingest, "fetch_series", fake_fetch)
    # neutralise all storage side effects
    monkeypatch.setattr(fred_ingest.load_fred, "get_connection", lambda *a, **k: DummyCon())
    monkeypatch.setattr(fred_ingest.load_fred, "ensure_schema", lambda con: None)
    monkeypatch.setattr(fred_ingest.load_fred, "upsert_dim", lambda con, s: None)
    monkeypatch.setattr(fred_ingest.load_fred, "load_observations", lambda con, sid, df: 0)
    monkeypatch.setattr(fred_ingest.load_fred, "record_status", lambda *a, **k: None)
    monkeypatch.setattr(fred_ingest.load_fred, "save_raw_parquet", lambda *a, **k: None)

    captured = {}
    monkeypatch.setattr(fred_ingest, "write_report",
                        lambda md, path: captured.update(md=md, path=path) or path)

    rc = fred_ingest.run(only=["DGS10", "CPIAUCSL"])
    assert rc == 0
    assert "**Result: PASS**" in captured["md"]
    assert "`DGS10`" in captured["md"] and "`CPIAUCSL`" in captured["md"]
    assert "Series attempted: **2**" in captured["md"]
