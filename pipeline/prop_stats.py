#!/usr/bin/env python3
"""
Pulls the historical stat lines that back a player prop pick, using nflverse-data
(free, no API key): L5 form, primetime hit rate, and opponent defense-vs-position rank.

Pure stdlib — no pandas/pip install needed, so it runs anywhere the pipeline agent does.

Data source: https://github.com/nflverse/nflverse-data
  - games.csv        season schedule incl. weekday/gametime (for primetime splits)
  - player_stats.csv weekly per-player stats back to 1999

Usage:
  python3 prop_stats.py --player "Puka Nacua" --opponent SF --stat receiving_yards --line 79.5

Prints a JSON blob with the numbers to back a report card. Caches the two source
CSVs in pipeline/.cache/ for a day so a week's worth of prop lookups only pulls
each file once.
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.request
from collections import defaultdict

GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
PLAYER_STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats.csv"
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
CACHE_MAX_AGE_SECONDS = 20 * 60 * 60  # ~20h, comfortably under a week

STAT_TO_POSITIONS = {
    "receiving_yards": {"WR", "TE", "RB"},
    "rushing_yards": {"RB", "QB", "WR"},
    "passing_yards": {"QB"},
    "receptions": {"WR", "TE", "RB"},
}


def _cached_download(url, filename):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, filename)
    if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < CACHE_MAX_AGE_SECONDS:
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


def is_primetime(game):
    """Thursday/Monday games, or a Sunday game with a night kickoff (SNF)."""
    weekday = game.get("weekday", "")
    gametime = game.get("gametime", "")
    if weekday in ("Thursday", "Monday", "Saturday"):
        return True
    if weekday == "Sunday" and gametime:
        try:
            hour = int(gametime.split(":")[0])
            return hour >= 18
        except ValueError:
            return False
    return False


def build_game_index(games):
    """(season, week, team) -> game row, for both home and away team."""
    index = {}
    for g in games:
        try:
            season, week = int(g["season"]), int(g["week"])
        except (ValueError, KeyError):
            continue
        index[(season, week, g["home_team"])] = g
        index[(season, week, g["away_team"])] = g
    return index


def player_rows(stats, player_name):
    needle = player_name.strip().lower()
    return [
        r for r in stats
        if r.get("player_display_name", "").strip().lower() == needle
        or r.get("player_name", "").strip().lower() == needle
    ]


def to_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def analyze(player_name, opponent_team, stat, line, seasons_back=3):
    games = load_games()
    stats = load_player_stats()
    game_index = build_game_index(games)

    rows = player_rows(stats, player_name)
    if not rows:
        return {"error": f"No player_stats rows found for '{player_name}'. Check spelling/name format."}

    rows.sort(key=lambda r: (int(r["season"]), int(r["week"])))
    position_group = rows[-1].get("position_group", "")

    # Last 5 games played (any slot)
    last5 = rows[-5:]
    last5_vals = [to_float(r.get(stat)) for r in last5]
    last5_hit = sum(1 for v in last5_vals if v > line)

    # Primetime split, trailing `seasons_back` seasons
    min_season = int(rows[-1]["season"]) - seasons_back
    primetime_vals = []
    for r in rows:
        if int(r["season"]) < min_season:
            continue
        g = game_index.get((int(r["season"]), int(r["week"]), r.get("recent_team")))
        if g and is_primetime(g):
            primetime_vals.append(to_float(r.get(stat)))
    primetime_hit = sum(1 for v in primetime_vals if v > line)

    # Opponent defense-vs-position rank, current season.
    # Standard "yards allowed per game to position" definition: sum the stat across
    # all eligible-position players in a single game, then average that per-game
    # total across games — NOT averaged per individual player appearance, which
    # would dilute the signal with WR3/WR4 clutter.
    current_season = int(rows[-1]["season"])
    eligible_positions = STAT_TO_POSITIONS.get(stat, {position_group})
    per_game_totals = defaultdict(lambda: defaultdict(float))  # team -> (season,week) -> total
    for r in stats:
        if int(r.get("season", 0)) != current_season:
            continue
        if r.get("position_group") not in eligible_positions:
            continue
        opp = r.get("opponent_team")
        if not opp:
            continue
        per_game_totals[opp][(r["season"], r["week"])] += to_float(r.get(stat))

    averages = {
        team: (sum(game_totals.values()) / len(game_totals) if game_totals else 0.0)
        for team, game_totals in per_game_totals.items()
    }
    ranked = sorted(averages.items(), key=lambda kv: kv[1], reverse=True)
    opp_rank = next((i + 1 for i, (team, _) in enumerate(ranked) if team == opponent_team), None)
    opp_avg_allowed = averages.get(opponent_team)

    season_vals = [to_float(r.get(stat)) for r in rows if int(r["season"]) == current_season]

    return {
        "player": player_name,
        "position_group": position_group,
        "stat": stat,
        "line": line,
        "l5_hit_rate": f"{last5_hit}/{len(last5_vals)}",
        "l5_values": last5_vals,
        "primetime_hit_rate": f"{primetime_hit}/{len(primetime_vals)}" if primetime_vals else "no primetime sample",
        "season_avg": round(sum(season_vals) / len(season_vals), 1) if season_vals else None,
        "opponent": opponent_team,
        "opponent_def_rank_vs_position": opp_rank,
        "opponent_def_avg_allowed": round(opp_avg_allowed, 1) if opp_avg_allowed is not None else None,
        "teams_ranked": len(ranked),
        "note": "opponent_def_rank_vs_position: 1 = allows the most to this position group (worst matchup for the defense, best for the prop)",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--player", required=True, help='e.g. "Puka Nacua"')
    ap.add_argument("--opponent", required=True, help="team abbrev this week's opponent, e.g. SF")
    ap.add_argument("--stat", required=True, choices=sorted(STAT_TO_POSITIONS.keys()))
    ap.add_argument("--line", required=True, type=float)
    ap.add_argument("--seasons-back", type=int, default=3)
    args = ap.parse_args()

    result = analyze(args.player, args.opponent, args.stat, args.line, args.seasons_back)
    print(json.dumps(result, indent=2))
    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
