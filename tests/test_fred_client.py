"""Tests for src/extract/fred_client.py — the network call is mocked, so these
run offline and instantly."""
from src.extract import fred_client
from src.extract.fred_client import fetch_series


class FakeResp:
    """Stand-in for a requests.Response."""
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _no_throttle(monkeypatch):
    monkeypatch.setattr(fred_client, "_throttle", lambda: None)


def test_parse_ok_and_drops_missing(monkeypatch):
    payload = {"observations": [
        {"date": "2024-01-01", "value": "3.9"},
        {"date": "2024-01-02", "value": "."},     # missing -> dropped
        {"date": "2024-01-03", "value": "4.0"},
    ]}
    _no_throttle(monkeypatch)
    monkeypatch.setattr(fred_client, "_http_get", lambda params: FakeResp(200, payload))
    r = fetch_series("DGS10", "key")
    assert r.status == "ok"
    assert r.n_obs == 2                            # the '.' row was dropped
    assert list(r.df["value"]) == [3.9, 4.0]


def test_bad_id_returns_error_not_exception(monkeypatch):
    _no_throttle(monkeypatch)
    monkeypatch.setattr(fred_client, "_http_get",
                        lambda params: FakeResp(400, {"error_message": "Bad series"}))
    r = fetch_series("NOTASERIES", "key")
    assert r.status == "error"
    assert "bad id" in r.error
    assert r.n_obs == 0


def test_empty_series(monkeypatch):
    _no_throttle(monkeypatch)
    monkeypatch.setattr(fred_client, "_http_get",
                        lambda params: FakeResp(200, {"observations": []}))
    r = fetch_series("X", "key")
    assert r.status == "empty"
    assert r.n_obs == 0


def test_server_error_retries_then_gives_up(monkeypatch):
    _no_throttle(monkeypatch)
    calls = {"n": 0}

    def flaky(params):
        calls["n"] += 1
        return FakeResp(503)

    monkeypatch.setattr(fred_client, "_http_get", flaky)
    # patch sleep so the backoff doesn't actually wait during the test
    monkeypatch.setattr(fred_client.time, "sleep", lambda s: None)
    r = fetch_series("X", "key", retries=3)
    assert r.status == "error"
    assert calls["n"] == 3                          # retried the full 3 times
