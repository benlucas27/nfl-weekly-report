#!/usr/bin/env python3
"""
Cross-references the CURRENT week's actual slate against every filter in
historical_screen.py and travel_and_clock.py, and reports which ones are both
(a) triggered by a real game this week and (b) an actual signal (cleared the edge
threshold in a fresh historical scan) — this is the "rotate through whichever of the
48 are live" step the runbook describes, made concrete instead of a manual judgment
call.

Usage:
  python3 this_week.py                  # auto-detects the current week
  python3 this_week.py --week 2 --season 2026
"""

import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))
from historical_screen import (  # noqa: E402
    load_games, enrich_games, FILTERS, run_filter, load_team_game_stats,
    is_signal as base_is_signal,
)
from travel_and_clock import (  # noqa: E402
    load_locations, annotate_distance, geo_filters, is_signal as geo_is_signal,
)


def current_week(games, season=None):
    """First week (by number) that still has an unscored REG game."""
    candidates = [g for g in games if g["game_type"] == "REG" and not g.get("home_score")]
    if season:
        candidates = [g for g in candidates if g["season"] == str(season)]
    if not candidates:
        return None, None
    best = min(candidates, key=lambda g: (int(g["season"]), int(g["week"])))
    return int(best["season"]), int(best["week"])


def week_games(games, season, week):
    return [g for g in games
            if g["game_type"] == "REG" and int(g["season"]) == season and int(g["week"]) == week]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int)
    ap.add_argument("--week", type=int)
    ap.add_argument("--min-n", type=int, default=60)
    ap.add_argument("--min-edge", type=float, default=0.07)
    ap.add_argument("--min-stat-edge", type=float, default=0.12)
    args = ap.parse_args()

    games = enrich_games(load_games())
    locations = load_locations()
    games = annotate_distance(games, locations)

    season, week = args.season, args.week
    if season is None or week is None:
        auto_season, auto_week = current_week(games, args.season)
        season, week = season or auto_season, week or auto_week
    if season is None or week is None:
        print(json.dumps({"error": "Could not auto-detect a current week — pass --season/--week."}))
        return

    slate = week_games(games, season, week)
    team_game_index = load_team_game_stats()

    # Which filters are real signals, evaluated fresh against the full historical set.
    signal_names = set()
    for name in FILTERS:
        result = run_filter(games, name, team_game_index)
        if base_is_signal(result, args.min_n, args.min_edge, args.min_stat_edge):
            signal_names.add(name)
    geo_results = geo_filters(games, team_game_index)
    geo_signals = {r["filter"]: r for r in geo_results
                   if geo_is_signal(r, args.min_n, args.min_edge, args.min_stat_edge)}

    hits = []
    for name in signal_names:
        _, pred = FILTERS[name]
        matches = [f"{g['away_team']} @ {g['home_team']}" for g in slate if pred(g)]
        if matches:
            hits.append({"filter": name, "matches": matches})

    for name, result in geo_signals.items():
        # geo filters were defined as simple lambdas inline in geo_filters(); re-derive
        # matches directly here since they're not stored on the result dict.
        if name == "cross_country_travel":
            matches = [f"{g['away_team']} @ {g['home_team']}" for g in slate if (g.get("_travel_miles") or 0) >= 1500]
        elif name == "cross_country_short_week":
            matches = [f"{g['away_team']} @ {g['home_team']}" for g in slate
                       if (g.get("_travel_miles") or 0) >= 1500 and (g.get("away_rest") and float(g["away_rest"]) <= 4)]
        elif name in ("denver_altitude_visitor", "denver_altitude_visitor_early_season"):
            matches = [f"{g['away_team']} @ {g['home_team']}" for g in slate if g.get("home_team") == "DEN"]
        else:
            matches = []
        if matches:
            hits.append({"filter": name, "matches": matches})

    print(json.dumps({
        "season": season, "week": week,
        "slate_size": len(slate),
        "signals_checked": len(signal_names) + len(geo_signals),
        "live_this_week": hits,
        "note": "Only filters that already cleared the edge threshold in a fresh full-history scan are checked here — this doesn't invent new signals, it just says which known ones apply to real games this week.",
    }, indent=2))


if __name__ == "__main__":
    main()
