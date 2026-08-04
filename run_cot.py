"""
CFTC positioning pipeline - load, test, transform in one command.

Ties together the pieces built for the positioning layer (Addition #2) so the whole
CFTC flow runs as a single step instead of three separate commands. Each stage is
just the existing module's own entry point; this file only sequences them and stops
at the first failure.

Run from the project root:

    python run_cot.py                 # load then transform
    python run_cot.py --preflight     # confirm market patterns first, then load + transform
    python run_cot.py --test          # load, run the CFTC tests, then transform
    python run_cot.py --full          # refetch full history on the load
    python run_cot.py --only sp500,vix
    python run_cot.py --skip-transform  # load only

Stages, in order: [preflight] -> load -> [test] -> transform.
The load stage needs the internet (it calls the CFTC API); the rest are local.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time

from src.common.cli import clean_argv

COT_TESTS = ["tests/test_cot_client.py", "tests/test_cot_load.py",
             "tests/test_cot_ingest.py", "tests/test_positioning.py"]


def _step(n, title):
    print(f"\n{'=' * 64}\n  Stage {n}: {title}\n{'=' * 64}")


def run(preflight=False, test=False, full=False, only=None, skip_transform=False) -> int:
    t0 = time.time()
    stage = 0

    # optional gate: confirm every manifest pattern resolves to a real contract
    if preflight:
        stage += 1
        _step(stage, "Preflight - confirm CFTC market patterns")
        from src.extract import cot_preflight
        if cot_preflight.main() != 0:
            print("\nPreflight found unresolved patterns. Fix config/cot_markets.yaml and re-run.")
            return 1

    # LOAD - ingest weekly positioning into stg_cot (needs the internet)
    stage += 1
    _step(stage, "Load - ingest CFTC positioning into stg_cot")
    from src.extract import cot_ingest
    rc = cot_ingest.run(only=only, full=full)
    if rc != 0:
        print("\nLoad failed - stopping before transform.")
        return rc

    # TEST - run the CFTC suite (self-contained: mocked network + in-memory db)
    if test:
        stage += 1
        _step(stage, "Test - run the CFTC test suite")
        rc = subprocess.call([sys.executable, "-m", "pytest", "-q", *COT_TESTS])
        if rc != 0:
            print("\nCFTC tests failed - stopping before transform.")
            return rc

    # TRANSFORM - build fct_positioning + fold positioning into the daily snapshot
    if skip_transform:
        print("\n--skip-transform set: loaded only, warehouse not rebuilt.")
    else:
        stage += 1
        _step(stage, "Transform - build fct_positioning + snapshot fold-in")
        from src.transform import run_transform
        rc = run_transform.run()
        if rc != 0:
            print("\nTransform failed.")
            return rc

    print(f"\nCFTC pipeline complete in {time.time() - t0:.1f}s.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the CFTC positioning pipeline (load, test, transform).")
    ap.add_argument("--preflight", action="store_true", help="confirm market patterns before loading")
    ap.add_argument("--test", action="store_true", help="run the CFTC test suite after loading")
    ap.add_argument("--full", action="store_true", help="refetch full history on the load")
    ap.add_argument("--only", help="comma-separated market ids (e.g. sp500,vix)")
    ap.add_argument("--skip-transform", action="store_true", help="load only; do not rebuild the warehouse")
    args = ap.parse_args(clean_argv())
    only = [x.strip() for x in args.only.split(",")] if args.only else None
    sys.exit(run(preflight=args.preflight, test=args.test, full=args.full,
                 only=only, skip_transform=args.skip_transform))


if __name__ == "__main__":
    main()
