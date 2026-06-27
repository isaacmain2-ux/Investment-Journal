#!/usr/bin/env python3
"""
Phase 0 setup doctor.

Run this ONCE, using VS Code's  Run button (top-right), from the
investment-journal project root. It checks every tool and every link between
them in a single pass and prints a PASS / WARN / FAIL line for each.

Running it via the VS Code Run button is itself a test: if it reports that the
virtual environment is active and the packages import, your VS Code interpreter
is correctly pointed at .venv.
"""
import sys
import os
import subprocess
import importlib
from pathlib import Path

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
ICON = {PASS: "\u2713", FAIL: "\u2717", WARN: "!"}
results = []


def record(name, status, detail=""):
    results.append((name, status, detail))
    line = f"  [{ICON[status]}] {name:<28} {status}"
    if detail:
        line += f"  -  {detail}"
    print(line)


def run(cmd):
    """Run a shell command; return (returncode, combined_output)."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return out.returncode, (out.stdout + out.stderr).strip()
    except FileNotFoundError:
        return 127, "command not found"
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


print("\n" + "=" * 58)
print("  PHASE 0 SETUP DOCTOR")
print("=" * 58)

# --- Are we in the project root? -------------------------------------------
in_root = any(Path(p).exists() for p in (".git", ".gitignore", "src", ".venv"))
if not in_root:
    record("Project root", WARN,
           "doesn't look like the project folder - cd into investment-journal/ first")
else:
    record("Project root", PASS, str(Path.cwd()))

# --- Python version ---------------------------------------------------------
v = sys.version_info
if v >= (3, 11):
    record("Python version", PASS, f"{v.major}.{v.minor}.{v.micro}")
else:
    record("Python version", FAIL, f"{v.major}.{v.minor} (need 3.11+)")

# --- Virtual environment active --------------------------------------------
in_venv = sys.prefix != getattr(sys, "base_prefix", sys.prefix)
is_dotvenv = ".venv" in sys.prefix
if in_venv and is_dotvenv:
    record("Virtual environment", PASS, "running inside .venv")
elif in_venv:
    record("Virtual environment", WARN, f"a venv is active but not .venv ({sys.prefix})")
else:
    record("Virtual environment", FAIL,
           "NOT in a venv - activate .venv, or use VS Code's Run button with .venv selected")

# --- Required packages ------------------------------------------------------
packages = {"duckdb": "duckdb", "pandas": "pandas",
            "pyarrow": "pyarrow", "python-dotenv": "dotenv"}
for label, module in packages.items():
    try:
        mod = importlib.import_module(module)
        ver = getattr(mod, "__version__", "?")
        record(f"Package: {label}", PASS, f"v{ver}")
    except Exception:  # noqa: BLE001
        record(f"Package: {label}", FAIL, "not importable in this environment")

# --- .env file and keys -----------------------------------------------------
env_exists = Path(".env").exists()
if env_exists:
    record(".env file", PASS, "found in project root")
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:  # noqa: BLE001
        pass
    for key in ("FRED_API_KEY", "ANTHROPIC_API_KEY"):
        val = os.environ.get(key, "")
        if val and "paste_your" not in val:
            record(f"  {key}", PASS, f"present ({len(val)} chars)")  # value never printed
        elif val:
            record(f"  {key}", WARN, "still the placeholder text - paste your real key")
        else:
            record(f"  {key}", FAIL, "missing from .env")
else:
    record(".env file", FAIL, "not found in project root")

# --- Warehouse read/write ---------------------------------------------------
wh = Path("data/warehouse.duckdb")
try:
    import duckdb
    Path("data").mkdir(exist_ok=True)
    con = duckdb.connect(str(wh))
    con.execute("CREATE TABLE IF NOT EXISTS _setup_check (msg VARCHAR)")
    con.execute("DELETE FROM _setup_check")
    con.execute("INSERT INTO _setup_check VALUES ('ok')")
    got = con.execute("SELECT msg FROM _setup_check").fetchone()[0]
    con.execute("DROP TABLE _setup_check")  # leave the warehouse clean
    con.close()
    record("Warehouse read/write", PASS if got == "ok" else FAIL, str(wh))
except Exception as exc:  # noqa: BLE001
    first = str(exc).splitlines()[0] if str(exc) else "unknown error"
    if "lock" in first.lower():
        first = "file is locked - close the DuckDB UI (or open it read-only) and retry"
    record("Warehouse read/write", FAIL, first)

# --- Folder skeleton --------------------------------------------------------
expected = ["config", "data/raw", "src/extract", "src/load",
            "src/transform", "src/analyze", "notebooks", "logs"]
missing_dirs = [d for d in expected if not Path(d).is_dir()]
if not missing_dirs:
    record("Folder skeleton", PASS, "all folders present")
else:
    record("Folder skeleton", WARN, "missing: " + ", ".join(missing_dirs))

# --- .gitignore protects secrets -------------------------------------------
gi = Path(".gitignore")
if gi.exists():
    txt = gi.read_text(encoding="utf-8", errors="ignore")
    record(".gitignore", PASS if ".env" in txt else WARN,
           "present and lists .env" if ".env" in txt else "present but doesn't list .env")
else:
    record(".gitignore", FAIL, "not found")

# --- requirements.txt -------------------------------------------------------
record("requirements.txt", PASS if Path("requirements.txt").exists() else WARN,
       "present" if Path("requirements.txt").exists()
       else "missing - run: pip freeze > requirements.txt")

# --- Git installed and configured ------------------------------------------
rc, out = run(["git", "--version"])
git_ok = rc == 0
record("Git installed", PASS if git_ok else FAIL,
       out if git_ok else "git not found on PATH")

if git_ok:
    _, name = run(["git", "config", "--global", "user.name"])
    _, email = run(["git", "config", "--global", "user.email"])
    if name and email:
        record("Git identity", PASS, f"{name} <{email}>")
    else:
        record("Git identity", WARN, "user.name / user.email not fully set")

    rc, _ = run(["git", "rev-parse", "--is-inside-work-tree"])
    repo_ok = rc == 0
    record("Git repository", PASS if repo_ok else FAIL,
           "this folder is a git repo" if repo_ok else "not a git repo yet")

    if repo_ok:
        _, remote = run(["git", "remote", "-v"])
        if remote and "github" in remote.lower():
            record("GitHub remote", PASS, "origin -> GitHub configured")
        elif remote:
            record("GitHub remote", WARN, "a remote exists but it isn't GitHub")
        else:
            record("GitHub remote", WARN, "no remote set (use 'Publish to GitHub' in VS Code)")

        # .env must NOT be tracked. rc==0 means it IS tracked (bad).
        if env_exists:
            rc, _ = run(["git", "ls-files", "--error-unmatch", ".env"])
            if rc == 0:
                record(".env protection", FAIL, "TRACKED by Git! run: git rm --cached .env")
            else:
                record(".env protection", PASS, ".env is not tracked by Git")

# --- DuckDB CLI (optional, for the browser UI) -----------------------------
rc, out = run(["duckdb", "--version"])
if rc == 0:
    record("DuckDB CLI", PASS, (out.splitlines()[0] if out else "installed"))
else:
    record("DuckDB CLI", WARN, "not on PATH (optional - powers 'duckdb -ui' browser view)")

# --- Summary ----------------------------------------------------------------
fails = sum(1 for _, s, _ in results if s == FAIL)
warns = sum(1 for _, s, _ in results if s == WARN)
print("-" * 58)
if fails == 0 and warns == 0:
    print("  RESULT: Everything checks out. Phase 0 is solid.")
elif fails == 0:
    print(f"  RESULT: No failures, {warns} warning(s). Warnings are usually")
    print("          optional items - review them above.")
else:
    print(f"  RESULT: {fails} failure(s), {warns} warning(s).")
    print("          Fix the [x] items above, then run this again.")
print("=" * 58 + "\n")