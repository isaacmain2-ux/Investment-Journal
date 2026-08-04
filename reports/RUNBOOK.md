# Options Skew — Runbook (Addition #3)

The volatility surface's shape across strikes — how much more the market pays for
downside puts than upside calls — from Yahoo option chains. Free, no key.

**The big difference from every other layer:** it's snapshot-only. Yahoo serves only
today's chain, so there's no history to backfill. Each run captures one row per
ticker and the warehouse **accumulates** over time. The percentile/z signals are thin
or blank at first and become meaningful after a few weeks of daily captures — so the
value is in starting it now and letting it run.

Everything here is tested offline. The one step my sandbox can't run is the live Yahoo
pull (no network) — that's the ingest, below.

---

## 1. Copy the files in (keep the folder structure)

**New files**
```
config\skew_tickers.yaml
src\extract\skew_client.py
src\extract\skew_ingest.py
src\extract\skew_preflight.py
src\load\load_skew.py
src\transform\sql\12_skew.sql
tests\test_skew_client.py
tests\test_skew_load.py
tests\test_skew_ingest.py
tests\test_skew_sql.py
tests\test_skew_fold.py
tests\test_skew_insights.py
```

**Overwrite (edited) files** — each adds to what's already there:
```
src\common\config.py       (adds load_skew_tickers / iter_skew_tickers)
src\common\reporting.py     (adds build_skew_report)
src\transform\derive.py     (adds skew_summary + snapshot fold-in)
src\report\queries.py       (gathers fct_skew)
src\report\sections.py      (adds the Skew section)
src\report\insights.py      (adds the tail-risk rules)
```

`yfinance` must be installed (`pip install yfinance` inside your `.venv`) — it's the
only new dependency, and it's imported lazily so the tests run without it.

> Note on `derive.py`: this copy is the cumulative latest — it already includes the
> CFTC positioning fold-in, the datetime-resolution fix, and the volatility regime
> axis from the polishes. Use this one.

---

## 2. Preflight (a live sanity check)

```
cd C:\Users\isaac\OneDrive\Desktop\Investment Journal
python -m src.extract.skew_preflight
```

This reaches Yahoo, samples the ~30-day expiry for each ticker, and prints the skew it
computed, e.g.:

```
  ok spx    SPY   exp 2026-09-04 (33d)  spot 512.40  put_skew +0.081  rr +0.121
  ok ndx    QQQ   exp 2026-09-04 (33d)  spot 470.10  put_skew +0.069  rr +0.098
```

If a ticker shows `empty` or `error`, Yahoo was flaky or returned a thin chain — it's
safe to just re-run; the source is unofficial and occasionally hiccups.

---

## 3. Capture (run this on a schedule)

```
python -m src.extract.skew_ingest
```

Each run appends today's capture to `stg_options_skew` (idempotent — running twice in a
day just replaces that day's row). **Run it daily** (a scheduled task) so history
accumulates. It writes a report to `reports\skew_ingest_<date>.md`.

---

## 4. Build + view

```
python -m src.transform.run_transform
python -m src.report.build_dashboard --open
```

`run_transform` builds `fct_skew` (it auto-detects the new SQL) and folds the latest
skew into the daily snapshot. The dashboard gains a **Skew** section — a latest-capture
table (put-skew, risk-reversal, ATM IV, z, percentile) and, once a few days have
accumulated, an SPY put-skew trend chart.

## 5. (Optional) tests

```
pytest -q
```

---

## What you'll see

- A **Skew** section. Early on the percentile/z columns will be blank — that's expected;
  they fill in as captures accumulate.
- Tail-risk insight flags, once there's enough history to rank against:
  - **Tail bid** (warn) — SPY put-skew steep vs its own history: crash protection bid.
  - **Skew complacent** (note) — put-skew unusually flat: little downside fear priced.
  - **Calm surface, nervous tails** (warn) — VIX historically low *and* skew elevated:
    the surface is calm but the wings are being hedged. This is the combined read with
    the vol layer, and the subtler cousin of the CFTC "fragile calm" flag.
  See `SAMPLE_skew_dashboard.html` for what a steep-skew day looks like.

## Notes

- **Snapshot-only.** No history until you accumulate it. The signals need a few weeks of
  daily runs before the percentiles mean anything.
- **Unofficial source.** Yahoo can be flaky; every stage is per-ticker and graceful, so a
  bad chain is skipped, never fatal.
- **Extending it** is a config edit: add a ticker to `skew_tickers.yaml`. Commodities or
  single stocks work too, though the tail-risk rules are tuned for the index (SPY).
