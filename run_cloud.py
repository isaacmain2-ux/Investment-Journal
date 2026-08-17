"""
Cloud daily runner — the single command GitHub Actions invokes.

Order: restore accumulated history -> ingest every layer -> transform -> build the
dashboard -> save accumulated history. Each stage runs as its own `python -m ...`
subprocess (so this file needs no knowledge of their internals), and a stage that
fails is logged and skipped rather than aborting the run — a flaky source (Yahoo,
most likely) shouldn't cost you the whole day's build. The dashboard is written into
`public/` and copied to `public/index.html` for GitHub Pages.

Exit code: 0 if the warehouse was transformed, the dashboard built, and the state
saved (even if an individual ingest hiccuped); 1 only if one of those core steps
failed — so you're emailed about real breakage, not a transient rate-limit.
"""
from __future__ import annotations

import glob
import shutil
import subprocess
import sys
import time
from pathlib import Path

from src.cloud import persist


def _step(desc, module_args) -> bool:
    print(f"\n{'=' * 60}\n  {desc}\n{'=' * 60}", flush=True)
    t0 = time.time()
    rc = subprocess.call([sys.executable, "-m", *module_args])
    ok = rc == 0
    print(f"  -> {desc}: {'OK' if ok else f'FAILED (rc={rc})'}  [{time.time() - t0:.0f}s]", flush=True)
    return ok


def _link_securities(index_path):
    """Inject a one-line link to the securities page into the macro dashboard."""
    import re
    try:
        with open(index_path, encoding="utf-8") as f:
            html = f.read()
        if "securities.html" in html:
            return
        banner = ('<div style="background:#2f6f4f;color:#fff;padding:8px 14px;'
                  'font:14px -apple-system,Segoe UI,sans-serif;text-align:center">'
                  '<a href="securities.html" style="color:#fff;font-weight:600;'
                  'text-decoration:none">Security selection screen \u2192</a></div>')
        html = re.sub(r'(<body[^>]*>)', r'\g<1>' + banner, html, count=1)
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:                       # noqa: BLE001
        print("  (could not add securities link:", e, ")")


def main() -> None:
    results: dict[str, bool] = {}

    # 1. restore accumulated history (creates the warehouse + seeds the 3 staging tables)
    print("\n=== restore accumulated state ===", flush=True)
    try:
        counts = persist.restore()
        print("  restored:", counts)
        results["Restore state"] = True
    except Exception as e:                      # noqa: BLE001
        print("  restore FAILED:", e)
        results["Restore state"] = False

    # 2. ingest every layer (rebuildable first, then the accumulating ones append today's)
    results["FRED macro + vol"] = _step("FRED macro + CBOE-vol series", ["src.extract.fred_ingest"])
    results["Equities"] = _step("Yahoo equities", ["src.extract.yf_ingest"])
    results["Fundamentals"] = _step("Fundamentals", ["src.extract.fundamentals_ingest"])
    results["Positioning"] = _step("CFTC positioning", ["src.extract.cot_ingest"])
    results["News"] = _step("FT headlines", ["src.extract.ft_ingest"])
    results["Skew"] = _step("Options skew (Yahoo)", ["src.extract.skew_ingest"])

    # 3. transform + dashboard
    results["Transform"] = _step("Transform (all gold tables + snapshot)", ["src.transform.run_transform"])
    results["Dashboard"] = _step("Dashboard", ["src.report.build_dashboard", "--out", "public"])

    # publish: copy the dated dashboard to index.html for GitHub Pages
    built = sorted(f for f in glob.glob("public/dashboard_*.html") if "securities" not in f)
    if built:
        shutil.copy(built[-1], "public/index.html")
        print(f"  published {built[-1]} -> public/index.html")
    else:
        print("  no dashboard HTML found to publish")
        results["Dashboard"] = False

    # 4. save accumulated history for the workflow to commit
    print("\n=== save accumulated state ===", flush=True)
    try:
        counts = persist.dump()
        print("  saved:", counts)
        results["Save state"] = True
    except Exception as e:                      # noqa: BLE001
        print("  dump FAILED:", e)
        results["Save state"] = False

    # 5. security-selection layer - rebuilds fresh each run (SEC + Yahoo both keep
    #    full history), so no persistence and no split-brain. Non-fatal: a hiccup here
    #    never blocks the macro dashboard.
    print("\n=== security-selection layer ===", flush=True)
    sec = True
    sec &= _step("Securities: ingest universe", ["src.extract.universe_ingest"])
    sec &= _step("Securities: metrics", ["src.transform.build_security_metrics"])
    sec &= _step("Securities: factors", ["src.transform.build_security_factors"])
    sec &= _step("Securities: dashboard", ["src.report.build_security_dashboard", "--out", "public"])
    sfiles = sorted(glob.glob("public/dashboard_securities_*.html"))
    if sfiles:
        shutil.copy(sfiles[-1], "public/securities.html")
        _link_securities("public/index.html")
        print(f"  published {sfiles[-1]} -> public/securities.html")
    else:
        sec = False
    results["Securities"] = sec

    # summary
    print("\n" + "=" * 60 + "\n  DAILY RUN SUMMARY")
    for name, ok in results.items():
        print(f"    {'ok  ' if ok else 'FAIL'}  {name}")
    print("=" * 60, flush=True)

    core_ok = results.get("Transform") and results.get("Dashboard") and results.get("Save state")
    if not results.get("Skew"):
        print("  NOTE: the options-skew capture did not succeed this run "
              "(often a transient Yahoo rate-limit from the cloud IP). "
              "History is preserved; it will retry tomorrow.")
    sys.exit(0 if core_ok else 1)


if __name__ == "__main__":
    main()