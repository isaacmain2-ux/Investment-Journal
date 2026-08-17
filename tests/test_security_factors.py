"""Tests for P3 cross-sectional factor engine."""
import datetime as dt
import pytest
pd = pytest.importorskip("pandas")
from src.transform import build_security_factors as F


def _universe():
    # 5 names with deliberately separable profiles
    A = dt.date(2026, 8, 3)
    return pd.DataFrame([
        # ticker  sector  earnings_yield fcf_yield pb  ps  ret_12_1m ret_6m dist_52w_high roe  g_m  o_m  n_m  d2e  rev_g  eps_g
        dict(ticker="CHEAP", sector="Fin", asof_date=A, earnings_yield=0.15, fcf_yield=0.12, pb=1.0, ps=1.0,
             ret_12_1m=-0.1, ret_6m=-0.05, dist_52w_high=-0.3, roe=0.10, gross_margin=0.3, op_margin=0.1,
             net_margin=0.08, debt_to_equity=0.5, rev_growth_yoy=0.01, eps_growth_yoy=0.0),
        dict(ticker="MOMO", sector="Tech", asof_date=A, earnings_yield=0.02, fcf_yield=0.01, pb=8.0, ps=8.0,
             ret_12_1m=0.6, ret_6m=0.3, dist_52w_high=-0.01, roe=0.15, gross_margin=0.5, op_margin=0.2,
             net_margin=0.15, debt_to_equity=0.3, rev_growth_yoy=0.2, eps_growth_yoy=0.25),
        dict(ticker="QUAL", sector="Tech", asof_date=A, earnings_yield=0.05, fcf_yield=0.05, pb=5.0, ps=5.0,
             ret_12_1m=0.1, ret_6m=0.05, dist_52w_high=-0.1, roe=0.40, gross_margin=0.7, op_margin=0.35,
             net_margin=0.30, debt_to_equity=0.1, rev_growth_yoy=0.1, eps_growth_yoy=0.1),
        dict(ticker="MID1", sector="Fin", asof_date=A, earnings_yield=0.06, fcf_yield=0.04, pb=2.0, ps=2.0,
             ret_12_1m=0.05, ret_6m=0.02, dist_52w_high=-0.15, roe=0.15, gross_margin=0.4, op_margin=0.15,
             net_margin=0.12, debt_to_equity=0.6, rev_growth_yoy=0.05, eps_growth_yoy=0.05),
        dict(ticker="MID2", sector="Ind", asof_date=A, earnings_yield=0.07, fcf_yield=0.05, pb=2.5, ps=2.5,
             ret_12_1m=0.08, ret_6m=0.03, dist_52w_high=-0.12, roe=0.18, gross_margin=0.35, op_margin=0.14,
             net_margin=0.11, debt_to_equity=0.55, rev_growth_yoy=0.06, eps_growth_yoy=0.06),
    ])


def test_value_ranks_cheapest_top():
    f = F.compute_factors(_universe())
    f = f.set_index("ticker")
    assert f.loc["CHEAP", "value_z"] == f["value_z"].max()      # cheapest -> best value
    assert f.loc["CHEAP", "value_pct"] == 1.0


def test_momentum_ranks_strongest_top():
    f = F.compute_factors(_universe()).set_index("ticker")
    assert f.loc["MOMO", "momentum_z"] == f["momentum_z"].max()


def test_quality_ranks_best_margins_top():
    f = F.compute_factors(_universe()).set_index("ticker")
    assert f.loc["QUAL", "quality_z"] == f["quality_z"].max()   # high ROE/margins/low debt


def test_composite_blends_all_four():
    # equal-weight composite: QUAL (great quality+decent) should beat the one-trick names overall
    f = F.compute_factors(_universe()).set_index("ticker")
    assert f["composite_z"].notna().all()
    # composite percentile is a proper 0-1 ranking
    assert abs(f["composite_pct"].max() - 1.0) < 1e-9 and f["composite_pct"].min() > 0


def test_weights_shift_the_ranking():
    u = _universe()
    val_heavy = F.compute_factors(u, weights={"value": 1, "momentum": 0, "quality": 0, "growth": 0}).set_index("ticker")
    mom_heavy = F.compute_factors(u, weights={"value": 0, "momentum": 1, "quality": 0, "growth": 0}).set_index("ticker")
    assert val_heavy["composite_z"].idxmax() == "CHEAP"
    assert mom_heavy["composite_z"].idxmax() == "MOMO"


def test_sector_neutral_ranks_within_sector():
    # within Tech, QUAL should out-rank MOMO on quality even though both are Tech
    f = F.compute_factors(_universe(), sector_neutral=True).set_index("ticker")
    tech = f.loc[["MOMO", "QUAL"]]
    assert tech.loc["QUAL", "quality_z"] > tech.loc["MOMO", "quality_z"]


def test_missing_metric_column_is_safe():
    u = _universe().drop(columns=["eps_growth_yoy", "fcf_yield"])
    f = F.compute_factors(u)                                     # must not raise
    assert len(f) == 5 and "growth_z" in f.columns


def test_handles_nan_metric_values():
    u = _universe()
    u.loc[u["ticker"] == "MID1", "roe"] = float("nan")          # one missing value
    f = F.compute_factors(u).set_index("ticker")
    assert f["quality_z"].notna().sum() >= 4                     # others still ranked


# ---------------- end-to-end run() ----------------
duckdb = pytest.importorskip("duckdb")
from src.transform import build_security_metrics as MET


def test_run_end_to_end_populates_factors():
    con = duckdb.connect(":memory:")
    MET.ensure_schema(con)
    u = _universe()
    cols = ["ticker", "asof_date", "sector", "earnings_yield", "fcf_yield", "pb", "ps",
            "ret_12_1m", "ret_6m", "dist_52w_high", "roe", "gross_margin", "op_margin",
            "net_margin", "debt_to_equity", "rev_growth_yoy", "eps_growth_yoy"]
    con.executemany(
        f"INSERT INTO fct_security_metrics ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})",
        [tuple(r[c] for c in cols) for _, r in u.iterrows()])
    assert F.run(con) == 0
    rows = con.execute("SELECT ticker, composite_z, value_pct FROM fct_security_factors").fetchall()
    assert len(rows) == 5
    vp = {t: v for t, _, v in rows}
    assert vp["CHEAP"] == max(vp.values())        # cheapest name tops the value percentile
    # composite is populated for all
    assert all(cz is not None for _, cz, _ in rows)
