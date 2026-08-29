#!/usr/bin/env python3
"""
Refreshes standings.json for the Footy Pool site.

Pulls current league points for every team in data/groups.json from
API-Football (https://www.api-football.com), matches them robustly
(not by scraping HTML — that's what broke the old Excel sheet), computes
each entrant's cumulative pool points from data/pool.json, and writes
docs/data/standings.json for the static site to render.

Requires env var API_FOOTBALL_KEY (set as a GitHub Actions secret).
Never silently zeroes a team it can't match — unmatched teams keep
their last known points and get flagged in "unmatched" so it shows
up on the page instead of quietly under-counting someone.
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import urllib.error
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
DOCS_DATA_DIR = os.path.join(ROOT, "docs", "data")
LEAGUE_CACHE_PATH = os.path.join(DATA_DIR, "league_ids.json")
GROUPS_PATH = os.path.join(DATA_DIR, "groups.json")
POOL_PATH = os.path.join(DATA_DIR, "pool.json")
OUT_PATH = os.path.join(DOCS_DATA_DIR, "standings.json")

API_BASE = "https://v3.football.api-sports.io"
API_KEY = os.environ.get("API_FOOTBALL_KEY")

DIVISIONS = {
    "EPL": {"name": "Premier League", "country": "England"},
    "EFL": {"name": "Championship", "country": "England"},
    "SPL": {"name": "Premiership", "country": "Scotland"},
}

NOISE_WORDS = {
    "fc", "afc", "city", "united", "town", "athletic", "albion",
    "hotspur", "county", "rovers", "wanderers", "and", "hove",
}


def api_get(path, params):
    if not API_KEY:
        print("ERROR: API_FOOTBALL_KEY is not set.", file=sys.stderr)
        sys.exit(1)
    url = f"{API_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"x-apisports-key": API_KEY})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.load(resp)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        print(f"DIAG: HTTPError {e.code} on {path} params={params}: {raw}", file=sys.stderr)
        return {"response": [], "errors": {"http_status": e.code, "body": raw}}
    errors = body.get("errors")
    if errors:
        print(f"DIAG: API errors on {path} params={params}: {errors}", file=sys.stderr)
    results_count = body.get("results")
    print(f"DIAG: {path} params={params} -> results={results_count} errors={errors}", file=sys.stderr)
    return body


def normalize(name):
    if not name:
        return ""
    s = name.lower()
    s = re.sub(r"[^a-z0-9\s]", "", s)
    words = [w for w in s.split() if w not in NOISE_WORDS]
    return " ".join(words) if words else s.strip()


def load_json(path, default=None):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def resolve_league_ids():
    cache = load_json(LEAGUE_CACHE_PATH, {})
    changed = False
    for code, info in DIVISIONS.items():
        if code in cache and "id" in cache[code] and "season" in cache[code]:
            continue
        resp = api_get("/leagues", {"name": info["name"], "country": info["country"]})
        results = resp.get("response", [])
        if not results:
            print(f"WARNING: could not resolve league id for {code} ({info['name']}, {info['country']})", file=sys.stderr)
            continue
        league = results[0]["league"]
        seasons = results[0]["seasons"]
        current = next((s for s in seasons if s.get("current")), seasons[-1] if seasons else None)
        if not current:
            print(f"WARNING: no season data for {code}", file=sys.stderr)
            continue
        cache[code] = {"id": league["id"], "season": current["year"], "name": league["name"]}
        changed = True
        time.sleep(1)
    if changed:
        save_json(LEAGUE_CACHE_PATH, cache)
    return cache


def fetch_standings(league_id, season):
    resp = api_get("/standings", {"league": league_id, "season": season})
    response = resp.get("response", [])
    if not response:
        return {}
    table_groups = response[0]["league"]["standings"]
    points = {}
    for table in table_groups:
        for row in table:
            team_name = row["team"]["name"]
            points[team_name] = row["points"]
    return points


def build_match_index(live_points):
    idx = {}
    for name, pts in live_points.items():
        idx[normalize(name)] = pts
    return idx


def match_points(team_name, live_points, norm_index):
    if team_name in live_points:
        return live_points[team_name], "exact"
    norm_name = normalize(team_name)
    if norm_name in norm_index:
        return norm_index[norm_name], "fuzzy"
    for live_name, pts in live_points.items():
        ln = normalize(live_name)
        if ln and (ln in norm_name or norm_name in ln):
            return pts, "contains"
    return None, "unmatched"


def main():
    groups = load_json(GROUPS_PATH, [])
    pool = load_json(POOL_PATH, [])
    prior = load_json(OUT_PATH, {"teams": []})
    prior_points = {t["team"]: t["points"] for t in prior.get("teams", [])}

    league_ids = resolve_league_ids()

    live_by_division = {}
    for code, cfg in league_ids.items():
        try:
            live_by_division[code] = fetch_standings(cfg["id"], cfg["season"])
        except Exception as e:
            print(f"WARNING: failed to fetch standings for {code}: {e}", file=sys.stderr)
            live_by_division[code] = {}

    team_rows = []
    unmatched = []
    for g in groups:
        division = g["division"]
        live_points = live_by_division.get(division, {})
        norm_index = build_match_index(live_points)
        pts, method = match_points(g["team"], live_points, norm_index)
        if pts is None:
            pts = prior_points.get(g["team"], 0)
            unmatched.append(g["team"])
        team_rows.append({
            "team": g["team"],
            "group": g["group"],
            "division": division,
            "points": pts,
            "match_method": method,
        })

    points_by_team = {t["team"]: t["points"] for t in team_rows}

    pool_totals = {}
    for entry in pool:
        pool_name = entry["pool"]
        total = sum(points_by_team.get(t, 0) for t in entry["picks"] if t)
        pool_totals.setdefault(pool_name, {"pool": pool_name, "entrant": entry["entrant"], "points": 0})
        pool_totals[pool_name]["points"] = total

    pools_sorted = sorted(pool_totals.values(), key=lambda x: -x["points"])
    rank = 0
    prev_points = None
    for i, row in enumerate(pools_sorted, start=1):
        if row["points"] != prev_points:
            rank = i
        row["standing"] = rank
        prev_points = row["points"]

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "teams": team_rows,
        "pools": pools_sorted,
        "unmatched_teams": unmatched,
    }
    save_json(OUT_PATH, out)
    print(f"Wrote {OUT_PATH}: {len(team_rows)} teams, {len(pools_sorted)} pools, {len(unmatched)} unmatched")
    if unmatched:
        print(f"UNMATCHED (kept prior value, flagged in UI): {unmatched}", file=sys.stderr)


if __name__ == "__main__":
    main()
