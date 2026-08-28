# Journal & Portfolio Tracking — Runbook (Addition #4)

Turns the platform from a market/screening dashboard into an actual hypothetical
investment journal: scan the latest factor scores for the strongest candidates,
confirm which ones you want to log, and track positions/portfolio value/P&L from
there — entirely from the terminal, no spreadsheet ever opened.

**The ledger is script-only.** `data/journal/trades.csv` is plain CSV, but it is
never hand-edited — `src/journal/ledger.py` is the only module that touches the
file, and it's only ever called by `add_trade.py`. See
`reports/Journal_Portfolio_Build_Plan.md` for the full design and the one deliberate
deviation from that plan (positions/portfolio value are built in Python, not SQL —
average-cost lot tracking is inherently sequential; see
`src/transform/journal_positions.py`'s docstring for why).

---

## 1. Copy the files in (keep the folder structure)

**New files**
```
src\journal\__init__.py
src\journal\ledger.py
src\journal\scan_candidates.py
src\journal\add_trade.py
src\load\load_journal.py
src\transform\journal_positions.py
tests\test_ledger.py
tests\test_scan_candidates.py
tests\test_add_trade.py
tests\test_load_journal.py
tests\test_journal_positions.py
tests\test_journal_positions_run.py
tests\test_journal_insights.py
```

**Overwrite (edited) files** — each adds to what's already there:
```
src\transform\run_transform.py   (loads the journal ledger before the SQL layer,
                                   builds positions/portfolio value after it)
src\transform\derive.py          (adds journal_summary + snapshot fold-in)
src\report\queries.py            (gathers stg_journal_trades, fct_positions,
                                   fct_portfolio_value, latest security closes)
src\report\sections.py           (adds the Journal section + a glance KPI)
src\report\insights.py           (adds the review-due / benchmark-gap /
                                   gone-quiet rules)
```

`data/journal/trades.csv` doesn't need to be seeded — it's created automatically
on the first `add_trade`. Nothing new to `pip install`; this addition only uses
pandas/duckdb, already dependencies.

---

## 2. Scan (read-only — see what the factor screen likes today)

```
cd C:\Users\isaac\OneDrive\Desktop\Investment Journal
python -m src.journal.scan_candidates
```

Prints the top 5 S&P 500 names by composite factor score as of the latest
`fct_security_factors` build, with the value/momentum/quality/growth breakdown and
last close — the same ranking `build_security_dashboard`'s "Best overall" tab
already uses, not a new engine. Already-open positions are excluded automatically.
Add `--n 10` for more names.

If the factors table is more than a few days stale, it says so — run
`python -m src.transform.run_transform` first.

---

## 3. Confirm and log (interactive — the only way the ledger gets written)

```
python -m src.journal.scan_candidates --log
```

Scans, then asks which row numbers to log (`1,3`, or `n` to skip). For each
confirmed name it prompts for quantity, price (defaults to the last close already
in the warehouse), conviction, timeframe, catalyst and tags, pre-fills the thesis
with the exact factor snapshot that justified the pick, and appends the row —
`csv.DictWriter`, no spreadsheet involved.

A trade outside the scanned list (a name you want to add for another reason):

```
python -m src.journal.add_trade --ticker AAPL --action BUY
```

---

## 4. Build + view

```
python -m src.transform.run_transform
python -m src.report.build_dashboard --open
```

`run_transform` now also: loads the ledger into `stg_journal_trades` (full refresh
from the CSV each run), builds `fct_positions` (current avg-cost/quantity per
ticker) and `fct_portfolio_value` (daily mark-to-market), and folds the main book's
value into the daily snapshot. The dashboard gains a **Journal** section — KPIs
(portfolio value, return since inception, unrealised/realised P&L, open positions),
an open-positions table, an equity curve vs. the S&P 500, and the trade log — plus
a "Journal value" tile on **At a glance**.

## 5. Tests

```
pytest -q
```

`test_ledger.py`, `test_scan_candidates.py` and `test_add_trade.py` need nothing
but pandas. `test_load_journal.py`, `test_journal_positions_run.py` and the
`duckdb`-backed cases in `test_report_build.py` need `duckdb` installed and skip
gracefully if it's not — this addition was built and tested in an environment with
no network access to install `duckdb`, so those specific cases could not be run
before delivery. Please run `pytest -q` once and let me know if anything in that
set fails — I'll fix it.

## What you'll see

- A **Journal** section, clearly labelled **Hypothetical** throughout — this is a
  paper book for testing decision quality, not a brokerage integration.
- Insight flags once there's a position or two: **Review due** (warn — down >15%
  since entry, or past its stated timeframe), **Journal is X% ahead/behind the
  S&P 500** (note, once there's enough history), **Journal gone quiet** (info — no
  new entries in 14+ days).

## Notes

- **Average-cost, not FIFO/specific-lot.** Deliberate — this is a journal, not a
  tax tool.
- **Single "main" book folded into the snapshot.** A second `portfolio` value in
  the ledger is tracked and shown in the Journal section's own tables, just not
  folded into the top-level snapshot KPI yet.
- **Corporate actions (splits)** aren't handled — a known limitation, same as the
  security-selection universe's own price data.
- **Deferred:** a "Thesis check" rule (comparing the frozen entry snapshot against
  today's factor read) needs a dedicated numeric field rather than parsing it back
  out of the free-text thesis — left for a follow-up rather than built on a fragile
  parse.

---

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
