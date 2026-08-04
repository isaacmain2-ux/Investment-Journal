# Options Skew — Build Plan (Addition #3)

*Adding the third dimension of the volatility surface — its shape across strikes —
from Yahoo Finance option chains. Complements VIX (the level of vol) and the term
structure (its shape over time) with the smile/smirk: how much more the market pays
for downside protection than upside.*

---

## 1. Objective

Capture equity-index **implied-volatility skew** — the premium of out-of-the-money
puts over calls — as a daily signal. A steep put skew means crash protection is
being bid (fear under the surface); a flat or inverted skew means complacency even
in the tails. Combined with the vol layer, it sharpens the "is the calm real?" read:
low VIX with *steepening* skew is calm on the surface but hedging underneath.

## 2. The source, and its one big caveat

Yahoo Finance option chains, via `yfinance`. Free, no key — but **unofficial and
snapshot-only**: Yahoo serves only the *current* chain, so unlike every other layer
this one has **no history**. It **accumulates**: each run captures today's skew and
the warehouse builds a history over time. The signals (percentile/z of skew) only
become meaningful after weeks of collection, which is the reason to start it now.

Because it's unofficial it's also the flakiest source on the platform — so every
stage is defensive and per-ticker: a failed or thin chain is logged and skipped,
never fatal.

## 3. The measures

From the chain nearest ~30 days to expiry, the client builds an IV-vs-moneyness
curve from the liquid out-of-the-money wings (puts below spot, calls above) and
interpolates IV at fixed moneyness levels:

| Measure | Definition |
|---|---|
| `atm_iv` | interpolated IV at 100% moneyness (spot) |
| `put_iv` | interpolated IV at 90% moneyness (OTM put) |
| `call_iv` | interpolated IV at 110% moneyness (OTM call) |
| `put_skew` | `put_iv − atm_iv` — downside premium over ATM |
| `risk_reversal` | `put_iv − call_iv` — downside vs upside |

All are pure functions of (spot, calls, puts); any that can't be computed from the
available strikes are null, never fabricated.

## 4. Point-in-time

Trivial here, and clean: each row *is* a snapshot as of its `capture_date`, so
there's no release lag to model. The daily-snapshot fold-in just uses the latest
capture on or before each date.

## 5. Architecture & files (mirrors the CFTC layer)

```
config/skew_tickers.yaml          NEW manifest: underlyings + target DTE + moneyness levels
src/common/config.py              + load_skew_tickers / iter_skew_tickers          [DONE, P1]
src/extract/skew_client.py        NEW yfinance seams + pure compute_skew            [DONE, P1]
src/load/load_skew.py             NEW stg_options_skew (snapshot-accumulating)      [P2]
src/extract/skew_ingest.py        NEW orchestrator                                  [P2]
src/extract/skew_preflight.py     NEW connectivity / chain-shape check              [P2]
src/transform/sql/12_skew.sql     NEW fct_skew (expanding z/percentile once history builds) [P3]
src/transform/derive.py           + skew_summary + snapshot fold-in                 [P4]
src/report/{queries,sections,insights}.py  + skew section & tail-risk rules         [P5]
build_hb.py                       + a Skew chapter                                  [P6]
tests/                            client, loader, model, insights                   [each milestone]
```

**Underlyings (default):** SPY (S&P 500), QQQ (Nasdaq 100), IWM (Russell 2000) —
SPY is the one that matters; the others are a config line each.

## 6. Milestones

| # | Milestone | Status |
|---|---|---|
| **P1** | manifest + config loader + `skew_client` (seams + `compute_skew`) + tests | **done, 8 tests green** |
| **P2** | `load_skew` (accumulating) + `skew_ingest` + `skew_preflight` + tests | next |
| **P3** | `12_skew.sql` — expanding percentile/z of skew (thin until history builds) | next |
| **P4** | snapshot fold-in (latest `put_skew` for SPY) | next |
| **P5** | dashboard section + tail-risk insight rules | next |
| **P6** | handbook chapter | next |

## 7. Insight rules (P5 preview)

- **Tail bid** — put skew steep vs its (accumulated) history: crash protection in demand.
- **Skew complacent** — put skew unusually flat: little downside fear priced.
- **Calm surface, nervous tails** (combined) — low VIX *and* steep/steepening skew:
  the surface is calm but the wings aren't, a subtler complacency signal than the vol
  layer alone.

## 8. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Yahoo unofficial / flaky | one lazy-imported seam per call; per-ticker graceful; snapshot-only so partial is fine |
| No history at first | measures work immediately; percentile/z stay null until enough captures accumulate |
| Thin/illiquid chains | OTM-wing filtering + bracket-required interpolation; degenerate chains return nulls |
| IV data quality (zeros/NaN) | filtered in `_pairs` before any maths |
| `yfinance` not importable in tests | seams import it lazily; the maths and fetch paths test fully offline |

## 9. Definition of done

`skew_ingest` accumulates daily skew into `stg_options_skew`; `fct_skew` builds and,
as history grows, carries percentile/z; the dashboard shows a skew section and the
tail-risk flags; `pytest -q` green; the handbook documents the source, its
snapshot-only nature, and the signals.

### One-line summary
A free (if unofficial) **options-skew layer** — the volatility surface's shape across
strikes — that accumulates its own history and adds a tail-risk dimension to the
platform's complacency read.
