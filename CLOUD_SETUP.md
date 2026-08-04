# Investment Journal → GitHub Actions — Setup Walkthrough

This runs your whole pipeline daily in GitHub's cloud and publishes the dashboard,
laptop off, at £0. Follow it top to bottom; it's about 20 minutes.

## What's in this package

```
requirements.txt              the exact packages the cloud installs
.gitignore                    keeps the warehouse/caches OUT, the state CSVs IN
run_cloud.py                  the one command the schedule runs (restore→ingest→build→save)
.github/workflows/daily.yml   the schedule + steps + Pages publish
src/cloud/persist.py          saves/loads the 3 accumulating tables as CSV
src/extract/skew_client.py    UPDATED - adds a browser session + retry/backoff for Yahoo
tests/test_skew_client.py     UPDATED - matching tests for the retry logic
```

Copy these into your project, keeping the folders. `skew_client.py` and its test
**overwrite** the existing ones; the rest are new.

## The idea in one line

Everything except news and options-skew is re-downloaded from its API each run;
those two (plus CFTC, to keep it fast) are saved as small CSVs in `data/state/` and
reloaded next run — so history accumulates in the cloud without your laptop.

---

## Step 1 — Create a GitHub account + repository

1. Sign up / sign in at github.com.
2. New repository → name it `investment-journal` → **Public** (this is what makes
   Pages and unlimited Actions minutes free) → Create repository.

> Public means the code and the dashboard are visible to anyone. Your data is
> aggregated public-market figures plus your own analysis — no account numbers — so
> this is normally fine. If you'd rather keep it private, say so and I'll give you the
> private-repo variant (Actions stays free; the dashboard is viewed a different way).

## Step 2 — Push your project up

From your project folder (with the new files copied in), in a terminal:

```
git init
git add .
git commit -m "Investment Journal - cloud version"
git branch -M main
git remote add origin https://github.com/<your-username>/investment-journal.git
git push -u origin main
```

## Step 3 — Add your FRED key as a secret

Repo → **Settings → Secrets and variables → Actions → New repository secret**
- Name: `FRED_API_KEY`
- Secret: paste your FRED key
- Add secret

(The code already reads `FRED_API_KEY` from the environment, so nothing else to change.)

## Step 4 — Give the workflow permission to save state

Repo → **Settings → Actions → General → Workflow permissions** →
select **Read and write permissions** → Save.
(This lets the daily run commit the updated `data/state/*.csv` back.)

## Step 5 — Turn on GitHub Pages

Repo → **Settings → Pages → Build and deployment → Source: GitHub Actions**.
(No branch to pick — the workflow publishes it.)

## Step 6 — Test it by hand

Repo → **Actions** tab → "Daily" workflow → **Run workflow** → Run.
Watch it: it should install, run the pipeline, commit state, and deploy Pages.
The first run creates `data/state/*.csv` and your dashboard site.

## Step 7 — Open your dashboard

After a green run, your dashboard is at:
```
https://<your-username>.github.io/investment-journal/
```
Open it from anywhere — phone, another computer, no laptop needed.

## Step 8 — Let it run itself

Nothing more to do. The `cron` line runs it **daily at 22:07 UTC** from now on. GitHub
emails you if a run fails.

---

## What to watch on the first few runs (the real test)

The one genuine unknown is whether Yahoo tolerates GitHub's shared IPs. In the run log
(Actions → the run → the "Run the pipeline" step), check the two Yahoo layers:

- **Equities** — if it's rate-limited, harmless: prices are re-fetchable, so a missed
  day self-heals.
- **Options skew (Yahoo)** — this is the one that matters, because it's snapshot-only.
  The summary at the bottom of the log shows `ok Skew` or `FAIL Skew`. The client now
  retries with backoff and a browser-like session to improve the odds. If it says
  `FAIL Skew` for a few days running, Yahoo is blocking the runner, and we move to the
  fallback (running just the skew capture from an always-on device on your home
  connection, everything else staying on GitHub). Your skew **history is never lost**
  either way — a failed day just doesn't add a row.

## Handy commands / checks

- See the schedule and history: the **Actions** tab.
- Re-run any time: **Run workflow** (the manual button).
- Confirm state is accumulating: after a few days, look at `data/state/*.csv` in the
  repo — the row counts should grow.

## Troubleshooting

- **Push step fails** ("permission denied"): re-check Step 4 (Read and write
  permissions).
- **Pages 404**: give the first deploy a minute; confirm Step 5 (Source: GitHub
  Actions) and that the run went green.
- **A dependency won't install**: tell me the error — we pin the version in
  `requirements.txt`.
- **FRED step says "not found"**: re-check the secret name is exactly `FRED_API_KEY`
  (Step 3).
- **Scheduled run didn't fire on time**: GitHub cron can lag at busy times; it usually
  catches up. The daily state commit keeps the schedule from being auto-disabled.

## Notes

- The default GitHub spending limit is **$0**, so this cannot bill you.
- CFTC, news and skew are saved as CSV so their runs stay incremental and their
  history persists; FRED, equities and fundamentals are rebuilt fresh from their APIs.
- Times are UTC (cron doesn't shift with BST/GMT); 22:07 UTC is after the US close.
