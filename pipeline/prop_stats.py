#!/usr/bin/env python3
"""
Pulls the historical stat lines that back a player prop pick, using nflverse-data
(free, no API key): L5 form, primetime hit rate, and opponent defense-vs-position rank.

Pure stdlib — no pandas/pip install needed, so it runs anywhere the pipeline agent does.

Data source: https://github.com/nflverse/nflverse-data
  - games.csv                     season schedule incl. weekday/gametime (for primetime splits)
  - stats_player_week_<year>.csv  weekly per-player stats, one file per season

NOTE: the older combined `player_stats.csv` release looks plausible (loads fine,
right shape) but stopped being updated in May 2025 — it silently serves 2022-2024
data as if current, with no error. Use `stats_player_week_<year>.csv` per season
instead (confirmed live for the current season) and concatenate the years you need.

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
import urllib.error
import time
import urllib.request
from collections import defaultdict

GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
STATS_WEEK_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{year}.csv"
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
CACHE_MAX_AGE_SECONDS = 20 * 60 * 60  # ~20h, comfortably under a week
STATS_YEARS_BACK = 4  # current season + 3 prior, enough for primetime/L5 history
DEF_WINDOW_GAMES = 17  # trailing games per defense for defense-vs-position rank

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
    """Concatenates stats_player_week_<year>.csv for the last STATS_YEARS_BACK
    seasons (auto-detected from today's date) rather than the stale combined file."""
    from datetime import date
    current_year = date.today().year
    rows = []
    for year in range(current_year - STATS_YEARS_BACK + 1, current_year + 1):
        url = STATS_WEEK_URL.format(year=year)
        try:
            path = _cached_download(url, f"stats_player_week_{year}.csv")
        except urllib.error.HTTPError:
            continue  # future season file may not exist yet
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                row["recent_team"] = row.get("team", row.get("recent_team"))  # column renamed upstream
                rows.append(row)
    return rows


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


def analyze(player_name, opponent_team, stat, line, seasons_back=3, expect_team=None):
    games = load_games()
    stats = load_player_stats()
    game_index = build_game_index(games)

    rows = player_rows(stats, player_name)
    if not rows:
        return {"error": f"No player_stats rows found for '{player_name}'. Check spelling/name format."}

    rows.sort(key=lambda r: (int(r["season"]), int(r["week"])))
    position_group = rows[-1].get("position_group", "")
    player_team = rows[-1].get("team") or rows[-1].get("recent_team")

    # Players change teams (free agency, trades) between and even within seasons —
    # this exact mistake (building a prop off a player's OLD team) put Kenneth Walker III
    # and Isiah Pacheco, both since-moved players, into the Week 4 2026 report tied to
    # games neither of them actually played in. --expect-team makes that a hard stop
    # instead of a silent bad pick: pass the team you believe this player is on, and a
    # mismatch fails loudly here rather than downstream in a published report.
    if expect_team and player_team and expect_team.strip().upper() != player_team.strip().upper():
        return {
            "error": (
                f"Team mismatch: you expected '{player_name}' to be on {expect_team.strip().upper()}, "
                f"but their most recent stats row has them on {player_team}. "
                f"Double-check the roster before using this player in a pick."
            ),
            "player_team": player_team,
        }

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

    # Opponent defense-vs-position rank over each defense's most recent
    # DEF_WINDOW_GAMES games (spanning seasons). Current-season-only is meaningless
    # early in the year (Week 2 = one game per team) and produced confident-sounding
    # matchup claims resting on a single game.
    # "Yards allowed per game to position" definition: sum the stat across all
    # eligible-position players in one game, then average those per-game totals.
    current_season = int(rows[-1]["season"])
    eligible_positions = STAT_TO_POSITIONS.get(stat, {position_group})
    per_game_totals = defaultdict(lambda: defaultdict(float))  # team -> (season,week) -> total
    for r in stats:
        if r.get("position_group") not in eligible_positions:
            continue
        opp = r.get("opponent_team")
        if not opp:
            continue
        per_game_totals[opp][(int(r["season"]), int(r["week"]))] += to_float(r.get(stat))

    averages = {}
    games_used = {}
    for team, game_totals in per_game_totals.items():
        recent = sorted(game_totals.items())[-DEF_WINDOW_GAMES:]
        games_used[team] = len(recent)
        averages[team] = sum(v for _, v in recent) / len(recent) if recent else 0.0
    ranked = sorted(averages.items(), key=lambda kv: kv[1], reverse=True)
    opp_rank = next((i + 1 for i, (team, _) in enumerate(ranked) if team == opponent_team), None)
    opp_avg_allowed = averages.get(opponent_team)

    season_vals = [to_float(r.get(stat)) for r in rows if int(r["season"]) == current_season]

    return {
        "player": player_name,
        "player_team": player_team,
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
        "opponent_def_games_in_window": games_used.get(opponent_team),
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
    ap.add_argument("--expect-team", help="team abbrev you believe this player is currently on, e.g. SEA — "
                                           "fails loudly on a mismatch instead of silently using a stale roster")
    args = ap.parse_args()

    result = analyze(args.player, args.opponent, args.stat, args.line, args.seasons_back, args.expect_team)
    print(json.dumps(result, indent=2))
    if "error" in result:
        sys.exit(1)


if __name__ == "__main__":
    main()
