# Journal & Portfolio Tracking — Build Plan

> **Status: built (P1–P6 delivered).** The code below now exists in the codebase —
> see `reports/RUNBOOK.md`'s "Journal & Portfolio Tracking — Runbook (Addition #4)"
> section for the copy-in / run / test steps. Two changes from the plan as originally
> written, both explained where they occur below: **positions and portfolio value are
> a Python module, not SQL** (§5), and **"Thesis check" (P6) was deferred**, not
> built (§7). Everything else matches. P7 (review refinements) is still open.

*Turning the platform from a market/screening dashboard into an actual investment
journal: a script that scans the latest factor scores for the strongest
candidates, a confirm-and-log step that writes a hypothetical trade to the
ledger without ever opening a spreadsheet, derived positions and mark-to-market
portfolio value, and a review layer that checks whether each thesis played out.
Follows the same shape as `Options_Skew_Build_Plan.md` — manifest/script →
loader → SQL → snapshot fold-in → dashboard section → insight rules — because
that shape has already proven itself twice (CFTC positioning, options skew).*

---

## 1. Objective

Every other layer in the platform answers "what is the market doing." None of
them answer "what did I do about it, and was I right." This adds that layer,
end to end:

1. **Scan** — as of the latest transform run, rank the universe and surface the
   5 highest-scoring securities.
2. **Confirm** — Isaac picks which of those (if any) he actually wants to log
   as a hypothetical trade, from the terminal.
3. **Record** — the confirmed trade is appended to the journal ledger
   automatically, with the reasoning captured at the moment of the decision,
   not reconstructed later.
4. **Track** — positions, portfolio value, and a benchmark comparison build
   from that ledger, and insight rules flag when a position is worth
   revisiting.

"Hypothetical" stays a first-class idea throughout: this is a paper book for
testing decision quality against data the platform already tracks — not a
brokerage integration. Nothing here blocks pointing it at real fills later; it
just isn't the job today.

## 2. The ledger, and how it actually gets written to

There's no API for "what Isaac decided" — but there also doesn't need to be a
hand-editing step. **The ledger is only ever written by script, never opened in
a spreadsheet.** `data/journal/trades.csv` is plain text (CSV needs nothing
from Microsoft Office to read or write — Python's own `csv` module handles it
natively) but the design goal here is stronger than "technically don't need
Excel": Isaac should never need to touch the file directly at all. Two small
scripts own it completely.

**`src/journal/scan_candidates.py`** — read-only. Pulls the latest
`asof_date` from `fct_security_factors` (the existing S&P 500 screening
engine that already powers the securities dashboard's "Best overall" tab —
this reuses that exact ranking, not a new one) and prints the top N by
`composite_z`, each with its value/momentum/quality/growth percentile
breakdown, sector, and last close, so the choice is informed rather than
guessed. Already-held tickers (from `fct_positions`, once it exists) are
excluded by default so it doesn't keep re-suggesting a name that's already in
the book.

```
$ python -m src.journal.scan_candidates
Top 5, S&P 500 universe, as of 2026-08-21 (composite_z, sector-neutral=off)

  1  NVDA   Technology       composite +1.82   value 41%  mom 97%  qual 88%  grow 95%   $187.40
  2  LLY    Health Care      composite +1.55   value 22%  mom 79%  qual 94%  grow 88%   $842.10
  3  CAT    Industrials      composite +1.31   value 68%  mom 71%  qual 66%  grow 74%   $412.55
  4  COST   Consumer Staples composite +1.24   value 12%  mom 85%  qual 91%  grow 61%   $981.20
  5  V      Financials       composite +1.19   value 55%  mom 62%  qual 89%  grow 58%   $321.75
```

**`src/journal/add_trade.py`** — interactive. Either runs after
`scan_candidates` (`--log` flag) so Isaac can answer with the row numbers he
wants ("1,3"), or takes a `--ticker` directly for a trade outside the scanned
list. For each confirmed name it prompts for quantity, price (defaulting to
the last close already in the warehouse, so a bare Enter accepts it),
conviction, timeframe, catalyst and tags, **pre-fills the thesis field with
the exact factor snapshot that justified the pick** ("Top-5 scan 2026-08-21:
composite +1.82 (91st pct) · value 41% · momentum 97% · quality 88% · growth
95%"), and lets Isaac extend it with his own free-text reasoning before it's
appended. It generates a stable `trade_id`, writes the row via `csv.DictWriter`
in append mode, and (optionally) re-runs `load_journal` so the warehouse
reflects it immediately.

```
$ python -m src.journal.scan_candidates --log
[... same table as above ...]
Add any to the journal? [row numbers, comma-separated, or 'n']: 1,3

NVDA — quantity: 10
  price [187.40]:
  conviction [medium]: high
  timeframe [months]:
  catalyst: datacenter capex guide-up
  thesis: Top-5 scan 2026-08-21: composite +1.82 (91st pct) · value 41% ·
          momentum 97% · quality 88% · growth 95%.
          + Riding the continued AI capex cycle into next earnings.
  tags: ai, momentum
  -> logged 2026-08-23-NVDA-01

CAT — quantity: 6
  ...
  -> logged 2026-08-23-CAT-01

2 trades appended to data/journal/trades.csv. Warehouse reloaded.
```

Isaac's interaction with the ledger, start to finish, is entirely inside the
terminal — the CSV itself never needs to be opened, edited, or even looked at
(though as plain text it's always readable in VS Code, Notepad, or GitHub's
web UI if he ever wants to).

## 3. The ledger schema

Written only by `add_trade.py`, never by hand:

| Field | Type | Notes |
|---|---|---|
| `trade_id` | VARCHAR (PK) | Auto-generated (`{date}-{ticker}-{seq}`), guarantees idempotent re-loads |
| `trade_date` | DATE | Defaults to today; overridable for a backfilled entry |
| `portfolio` | VARCHAR | Defaults to `main`; a second book is free later |
| `ticker` | VARCHAR | Always sourced from the scan list or validated against `dim_security` — never free-typed into the file |
| `action` | VARCHAR | `BUY` \| `SELL` |
| `quantity` | DOUBLE | Prompted |
| `price` | DOUBLE | Defaults to the latest close already in the warehouse |
| `currency` | VARCHAR | Filled from `dim_security`, not asked |
| `fees` | DOUBLE | Optional, defaults 0 |
| `conviction` | VARCHAR | low / medium / high, prompted |
| `timeframe` | VARCHAR | weeks / months / years, prompted |
| `catalyst` | VARCHAR | Free text, prompted |
| `thesis` | TEXT | **Pre-filled with the factor snapshot at scan time**, extendable |
| `tags` | VARCHAR | Comma-separated, prompted |
| `entered_at` | TIMESTAMP | Stamped automatically |

## 4. Point-in-time

Because the thesis snapshot is captured **at the moment of the scan**, not
reconstructed afterwards, the usual point-in-time risk (asking "what did the
factor score say back then?" and accidentally answering with today's
recomputed number) doesn't arise here — the answer is written straight into
the row. The SQL layer still ASOF-joins `trade_date` onto `fct_factor_scores`
and `fct_valuation` for the **review** step (Section 7), which compares the
frozen entry snapshot against *today's* numbers — that's the one place a
live, current-day join is actually wanted.

## 5. Architecture & files

| File | Purpose | Milestone |
|---|---|---|
| `data/journal/trades.csv` | NEW ledger — script-written only | P1 |
| `src/load/load_journal.py` | NEW `stg_journal_trades` schema + idempotent loader | P1 |
| `src/journal/scan_candidates.py` | NEW — pure `top_candidates(df, n, exclude)` ranking function + CLI table, reuses `fct_security_factors` (the same table `build_security_dashboard`'s "Best overall" screen already sorts) | P2 |
| `src/journal/add_trade.py` | NEW — interactive confirm/prompt flow, thesis auto-fill, `trade_id` generation, CSV append, optional warehouse reload | P3 |
| `src/transform/journal_positions.py` | **Changed from the original plan's `13_positions.sql`/`14_portfolio.sql`.** NEW `fct_positions` (running quantity & average cost per (portfolio, ticker), realised P&L per sell) and `fct_portfolio_value` (daily mark-to-market via a per-ticker as-of merge onto price history, unrealised P&L, portfolio return series) — built as pure, pandas-testable Python functions plus a thin warehouse-writing `run(con)`, not SQL. **Why:** average-cost lot tracking is inherently sequential — a SELL's realised P&L and the resulting average cost depend multiplicatively on the running state built up by every prior trade for that ticker. That isn't expressible as a plain SQL window-function cumulative sum without either `WITH RECURSIVE` or a row-by-row fold; `derive.py` already established the precedent for exactly this situation in this codebase ("this needs cross-series alignment ... which pandas does cleanly"), so this follows that precedent instead of forcing a recursive CTE. | P4 + P5 |
| `src/transform/derive.py` | + `journal_summary()` / `_fold_journal()` — folds portfolio value / open-position count / unrealised & realised P&L into `fct_daily_snapshot`, same pattern as `skew_summary` | P6 |
| `src/report/queries.py` | + gather `fct_positions`, `fct_portfolio_value`, `stg_journal_trades`, latest security closes | P6 |
| `src/report/sections.py` | + a **Journal** section: KPI tiles, open-positions table, equity-curve chart, trade log; + a "Journal value" tile on **At a glance** | P6 |
| `src/report/insights.py` | + Review due, Benchmark gap, Journal gone quiet rules (Thesis check deferred — see §7) | P6 |
| `tests/` | `test_ledger.py`, `test_load_journal.py`, `test_scan_candidates.py`, `test_add_trade.py`, `test_journal_positions.py` (pure functions), `test_journal_positions_run.py` (warehouse wiring), `test_journal_insights.py` | each milestone |

## 6. Milestones

| # | Milestone | What "done" looks like |
|---|---|---|
| **P1** | Ledger schema + `load_journal.py` + tests | A seeded `trades.csv` loads into `stg_journal_trades`; re-running the loader doesn't duplicate rows |
| **P2** | `scan_candidates.py` | Running it prints the top 5 by `composite_z` as of the true latest `asof_date`, with the factor breakdown, against a synthetic `fct_security_factors` frame in tests |
| **P3** | `add_trade.py` | The full scan → confirm → log flow appends a correctly-formed, thesis-populated row to `trades.csv` with no manual file editing; tested with simulated stdin |
| **P4** | `journal_positions.py` — positions | `fct_positions` shows correct running quantity and average cost across a buy → add → partial-sell sequence; realised P&L on the sell matches hand-calculation (verified directly with pandas — `test_journal_positions.py` runs green) |
| **P5** | `journal_positions.py` — portfolio value | `fct_portfolio_value` has one row per (portfolio, date) with market value, unrealised P&L, and a return series that rebases cleanly to 100 (verified directly with pandas — `test_journal_positions.py` runs green) |
| **P6** | Snapshot fold-in + dashboard section + insight rules | **At a glance** carries portfolio KPIs; a **Journal** section renders open positions, equity curve vs. S&P 500, and trade log; review-prompt insights fire on seeded data |
| **P7** | Review refinements (optional, can slip to Later) | A `fct_journal_review` table comparing each position's frozen entry snapshot against today's factor/valuation read, surfaced as "then vs. now" |

## 7. Dashboard & insight rules (P6 preview)

**Journal section, in the same visual language as the rest of the dashboard:**

- KPI row (reusing `sections.kpi()` + `charts.sparkline()`): portfolio value,
  total return since inception, unrealised P&L, realised P&L, open positions
- Open-positions table: ticker · qty · avg cost · current price · unrealised
  P&L % · days held · conviction · thesis (truncated, full text on
  hover/expand)
- Equity curve: portfolio value rebased to 100 alongside the S&P 500 rebased
  to 100 — reuses `charts.line(..., rebase=True)` outright, no new charting
  code needed
- Trade log: most recent entries, thesis included, same card/table pattern as
  **Headlines**

**Insight rules (same severity taxonomy as the rest of `insights.py`):**

- **Review due** (WARN) — a position is down beyond a threshold (−15%)
  since entry, or has passed its stated `timeframe`. *Built.*
- **Benchmark gap** (NOTE) — portfolio return vs. S&P 500 since inception,
  once there's enough history to be meaningful. *Built.*
- **Journal gone quiet** (INFO) — no new entries in 14 days. *Built.*
- **Thesis check** (NOTE) — the composite factor score has moved materially
  since entry, comparing the frozen snapshot in `thesis` against today's
  `fct_factor_scores`/`fct_security_factors` read for the same ticker.
  **Deferred, not built.** The frozen snapshot only exists as free text inside
  `thesis` — reliably parsing a specific `composite_z` back out of that string is
  fragile (it's meant for a human to read, not a machine to re-parse), so this
  needs a dedicated numeric column (e.g. `entry_composite_z`) added to the ledger
  schema first rather than being bolted onto the current one. Left for P7.

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Scan runs against stale factors (transform not rebuilt today) | `scan_candidates` prints the `asof_date` prominently and warns if it's more than one trading day old, the same staleness idea already used in the dashboard's Data health section |
| Average-cost vs. specific-lot/FIFO accounting | Average-cost is the deliberate choice — this is a journal, not a tax tool |
| Corporate actions (splits) | Prices elsewhere are auto-adjusted; a real split needs a manual adjustment row for now — a known limitation, not solved in P1–P7 |
| FX consistency | Reuse `fct_fx` exactly as `fct_valuation` already does |
| Bad ticker or duplicate trade | No longer a real risk once `add_trade.py` owns the file: tickers only ever come from the scan list or a `dim_security`-validated CLI input, and `trade_id` generation plus delete-and-reinsert load keeps re-runs idempotent |
| Confusing hypothetical with real money | A visible "hypothetical" label on the section itself, always |

## 9. Definition of done

`python -m src.journal.scan_candidates` prints the top 5 by composite score as
of the latest transform date; `python -m src.journal.scan_candidates --log`
(or `add_trade.py` directly) lets Isaac confirm one or more and appends a
fully-formed, thesis-populated row to `trades.csv` without opening any
spreadsheet software; `fct_positions` and `fct_portfolio_value` reconcile
against hand-calculation for a small test sequence; the dashboard shows a
**Journal** section with KPIs, an open-positions table, and an equity curve;
the review-prompt insight rules fire correctly against seeded data; `pytest -q`
green; `RUNBOOK.md` gets a short section describing the scan → confirm → log
workflow.

**Verification note:** every pure-Python piece above (`ledger`, `scan_candidates`,
`add_trade`, and — critically — the average-cost/mark-to-market math in
`journal_positions.py`) was written *and executed* against `pytest` with real
assertions (73 tests, all green) before delivery. The pieces that need `duckdb`
specifically (`load_journal.py`'s warehouse writes, `journal_positions.run()`'s
warehouse wiring, the new gathers in `queries.py`) were built by mirroring
`load_fred.py`/`load_skew.py`/`derive.py`'s exact, already-proven patterns, and
their tests are written and included (`pytest.importorskip("duckdb")`, same
convention as the rest of the suite) — but couldn't be executed in the environment
this was built in (no network access to install `duckdb`). Please run `pytest -q`
once locally and send back anything that fails — I'll fix it immediately.

### One-line summary
A scan-confirm-log workflow, not a spreadsheet: `scan_candidates.py` ranks the
universe by the platform's own factor scores, `add_trade.py` turns a confirmed
pick into a fully-reasoned ledger row with zero manual file editing, and the
existing manifest → loader → SQL → snapshot → dashboard shape (already used
twice) carries it the rest of the way into an actual investment journal.
