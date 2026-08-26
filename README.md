# Footy Pool 26/27 — auto-updating standings site

Free, no-subscription static site (GitHub Pages) with data pulled from
API-Football on a schedule (GitHub Actions), so nobody has to open Excel
or a web browser to refresh scores. The workbook stays as your offline
backup / audit copy — this doesn't replace it, it automates it.

## What's in here

- `docs/index.html` — the page itself (two sortable tables: pool standings,
  team points by group). Served by GitHub Pages straight from `/docs`.
- `docs/data/standings.json` — the data the page reads. Seeded with the
  Aug 26 2026 audit snapshot; overwritten by every scheduled refresh.
- `data/pool.json` — every entrant's picks, pulled from the Picks tab.
- `data/groups.json` — team → group/division mapping, pulled from the Groups tab.
- `data/league_ids.json` — cache of API-Football's league IDs (auto-created
  on first run, so the script doesn't burn API calls re-discovering them).
- `scripts/refresh.py` — fetches live standings, matches team names
  robustly (never silently zeroes an unmatched team — see below), recomputes
  both tables, writes `docs/data/standings.json`.
- `.github/workflows/refresh.yml` — runs `refresh.py` every 3 hours and on
  demand, commits the updated JSON.

## One-time setup (about 10 minutes)

1. **Create a free GitHub account** if you don't have one: github.com/join.

2. **Create a new repository** (Settings can stay default — Public is fine
   for a free pool site; Private also works, Pages is free either way).
   Name it whatever you like, e.g. `footy-pool`.

3. **Upload these files** into that repo, preserving the folder structure
   exactly as it is here (`docs/`, `data/`, `scripts/`, `.github/workflows/`).
   Easiest way: on the repo's GitHub page, use "Add file → Upload files"
   and drag the whole folder in, or use GitHub Desktop if you'd rather
   work locally.

4. **Get a free API-Football key** (no credit card required):
   - Go to https://www.api-football.com, sign up for the free plan
     (100 requests/day — plenty for a refresh every 3 hours).
   - Copy your API key from the dashboard.

5. **Add the key as a repo secret** (GitHub never exposes this publicly):
   - In your repo: Settings → Secrets and variables → Actions →
     "New repository secret"
   - Name: `API_FOOTBALL_KEY`
   - Value: paste your key
   - Save.

6. **Turn on GitHub Pages**:
   - Settings → Pages
   - Source: "Deploy from a branch"
   - Branch: `main`, folder: `/docs`
   - Save. GitHub will give you a URL like
     `https://<your-username>.github.io/footy-pool/` — that's your live page.

7. **Run the refresh once manually** to confirm it works:
   - Go to the "Actions" tab → "Refresh standings" workflow →
     "Run workflow" → Run workflow.
   - Watch it go green. If it goes red, click into it — the log will say
     exactly what failed (usually a missing/misspelled secret name).

After that, it refreshes itself every 3 hours automatically. No manual
edits, no reopening Excel, no web-scrape-breaks-on-a-crest-icon problem —
this pulls structured JSON from an API, not a rendered webpage.

## Why this doesn't repeat the Brighton bug

The old workbook scraped Sky Sports' HTML table, where a leader-row badge
apparently broke the name extraction for whoever topped the table that
week — silently, with no warning, understating everyone who'd picked that
team. This build pulls structured data (team name + points as plain JSON
fields, not parsed HTML), and if a team name still fails to match for any
reason, `refresh.py` does **not** zero it — it keeps the last known value
and adds it to `unmatched_teams`, which the page displays as a visible
warning banner. You'll see a problem instead of quietly losing points.

## Adjusting the refresh frequency

Edit the `cron` line in `.github/workflows/refresh.yml`. Current setting
(`0 */3 * * *`) is every 3 hours — comfortably inside the 100-request/day
free-tier budget (3 divisions × 8 refreshes/day = 24 calls/day, plus a
few one-time league-lookup calls).

## If a team's group assignment or a pick changes mid-season

Edit `data/groups.json` or `data/pool.json` directly in the repo (or
re-export from the workbook and re-upload) — the next scheduled or manual
refresh picks up the change automatically.
