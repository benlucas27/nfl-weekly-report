#!/usr/bin/env python3
"""
Finds historical betting-market patterns for a defined "situation" — e.g. "teams
debuting a brand-new stadium" — by joining a curated instance list (pipeline/situations/*.json)
against nflverse-data (games.csv, player_stats.csv). Free, no API key, stdlib only.

This is the general tool behind questions like: "since 2000, how do run games and
totals behave when a team plays its first game in a new stadium?"

Usage:
  python3 situational_splits.py --situation new_stadium_debut --scope opener
  python3 situational_splits.py --situation new_stadium_debut --scope season

--scope opener  -> only the very first home game of that debut season (small n,
                   isolates the "grand opening" effect)
--scope season  -> every home game in the debut season (bigger n, dilutes the
                   opening-night-specific effect but shows the fuller pattern)

Prints a JSON summary: total/over-under record, and the lead rusher's debut-game
output vs their own season baseline (excluding that game). Always read the `notes`
and small-sample caveats before treating this as a real lean — these are cohort
sizes in the tens of games, not thousands.
"""

import argparse
import csv
import json
import os
import sys
import urllib.request
from collections import defaultdict

GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
PLAYER_STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv"
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
SITUATIONS_DIR = os.path.join(os.path.dirname(__file__), "situations")


def _cached_download(url, filename):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, filename)
    if os.path.exists(path):
        return path
    req = urllib.request.Request(url, headers={"User-Agent": "nfl-weekly-report/1.0"})
    with urllib.request.urlopen(req) as resp, open(path, "wb") as out:
        out.write(resp.read())
    return path


def load_games():
    path = _cached_download(GAMES_URL, "games.csv")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_player_stats():
    path = _cached_download(PLAYER_STATS_URL, "player_stats.csv")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def to_float(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def load_situation(name):
    path = os.path.join(SITUATIONS_DIR, f"{name}.json")
    if not os.path.exists(path):
        available = [f[:-5] for f in os.listdir(SITUATIONS_DIR) if f.endswith(".json")]
        raise SystemExit(f"Unknown situation '{name}'. Available: {available}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def team_home_games(games, team, season):
    rows = [g for g in games if g["home_team"] == team and int(g["season"]) == season and g.get("game_type") == "REG"]
    rows.sort(key=lambda g: int(g["week"]))
    return rows


def lead_rusher(stats, team, season, exclude_week=None):
    """The RB with the most total rushing yards for a team/season, and their per-week values."""
    by_player = defaultdict(list)
    for r in stats:
        if r.get("recent_team") != team or int(r.get("season", 0)) != season:
            continue
        if r.get("position_group") != "RB":
            continue
        by_player[r.get("player_display_name")].append(r)

    if not by_player:
        return None

    lead_name = max(by_player, key=lambda name: sum(to_float(r.get("rushing_yards"), 0) for r in by_player[name]))
    rows = sorted(by_player[lead_name], key=lambda r: int(r["week"]))
    return lead_name, rows


def analyze(situation_name, scope):
    situation = load_situation(situation_name)
    games = load_games()
    stats = load_player_stats()

    total_results = []  # "over" | "under" | "push"
    rb_deltas = []
    instance_details = []

    for inst in situation["instances"]:
        team, season = inst["team"], inst["season"]
        home_games = team_home_games(games, team, season)
        if not home_games:
            continue
        target_games = [home_games[0]] if scope == "opener" else home_games

        for g in target_games:
            week = int(g["week"])
            total_line = to_float(g.get("total_line"))
            actual_total = to_float(g.get("total"))
            over_under = None
            if total_line is not None and actual_total is not None:
                over_under = "over" if actual_total > total_line else ("under" if actual_total < total_line else "push")
                total_results.append(over_under)

            lead = lead_rusher(stats, team, season)
            rb_note = None
            if lead:
                name, rows = lead
                this_week = next((r for r in rows if int(r["week"]) == week), None)
                baseline_rows = [r for r in rows if int(r["week"]) != week]
                if this_week and baseline_rows:
                    baseline_avg = sum(to_float(r.get("rushing_yards"), 0) for r in baseline_rows) / len(baseline_rows)
                    this_val = to_float(this_week.get("rushing_yards"), 0)
                    delta = round(this_val - baseline_avg, 1)
                    rb_deltas.append(delta)
                    rb_note = {"player": name, "this_game": this_val, "season_baseline": round(baseline_avg, 1), "delta": delta}

            instance_details.append({
                "team": team, "season": season, "week": week,
                "opponent": g.get("away_team"),
                "total_line": total_line, "actual_total": actual_total, "result": over_under,
                "lead_rb": rb_note,
                "notes": inst.get("notes"),
            })

    over_n = total_results.count("over")
    under_n = total_results.count("under")
    push_n = total_results.count("push")

    return {
        "situation": situation_name,
        "scope": scope,
        "sample_size_games": len(instance_details),
        "caveat": "Small-sample situational cohort — read as a data point, not a proven edge.",
        "totals": {
            "over": over_n, "under": under_n, "push": push_n,
            "over_rate": round(over_n / len(total_results), 2) if total_results else None,
        },
        "lead_rb_vs_own_season_baseline": {
            "n": len(rb_deltas),
            "avg_delta_yards": round(sum(rb_deltas) / len(rb_deltas), 1) if rb_deltas else None,
            "pct_above_baseline": round(sum(1 for d in rb_deltas if d > 0) / len(rb_deltas), 2) if rb_deltas else None,
        },
        "instances": instance_details,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--situation", required=True, help="e.g. new_stadium_debut")
    ap.add_argument("--scope", choices=["opener", "season"], default="opener")
    args = ap.parse_args()

    result = analyze(args.situation, args.scope)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
