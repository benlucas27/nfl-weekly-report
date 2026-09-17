#!/usr/bin/env python3
"""
Geography/timezone-derived situational angles — the ones historical_screen.py can't
do because they need a team-location lookup, not just schedule columns:

  - cross_country_travel     away team traveling 1500+ miles for this game
  - cross_country_short_week same, and on <=4 days rest
  - denver_altitude_visitor  visiting team at Denver's elevation (all games, and
                              early-season only, since that's the specific claim
                              floated in NFL home-field-advantage commentary)
  - bodyclock_primetime      the "West Coast teams have a circadian edge in
                              8pm ET+ kickoffs" claim (Smith et al. 2013/2018,
                              widely cited in NFL handicapping content) — tested
                              from the advantaged TEAM's own perspective (win/cover
                              record, whichever side of the game they're on), not
                              fixed to home or away

Uses the same nflverse-data games.csv as historical_screen.py, plus
pipeline/team_locations.json (hand-compiled, approximate). Reuses
historical_screen.py's outcome/edge helpers rather than reimplementing them.

Usage:
  python3 travel_and_clock.py --scan
  python3 travel_and_clock.py --filter cross_country_travel
  python3 travel_and_clock.py --bodyclock
"""

import argparse
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from historical_screen import (  # noqa: E402
    load_games, load_team_game_stats, outcomes, edge, to_float, stderr,
    stat_summary, stat_edges, strength as _base_strength,
)


def is_signal(result, min_n, min_edge, min_stat_edge):
    """Like historical_screen.is_signal, but also checks away_win_rate_edge_vs_baseline
    — a field these geo filters carry that the base version doesn't know about."""
    if result["cohort"]["n"] < min_n:
        return False
    for edge_key in ("over_under_edge_vs_baseline", "home_ats_edge_vs_baseline", "away_win_rate_edge_vs_baseline"):
        e = result.get(edge_key)
        if e is not None and abs(e) >= min_edge:
            return True
    for side in ("home_team_volume", "away_team_volume"):
        for e in result[side]["relative_edge"].values():
            if e is not None and abs(e) >= min_stat_edge:
                return True
    return False


def strength(result):
    s = _base_strength(result)
    away_win_edge = result.get("away_win_rate_edge_vs_baseline")
    if away_win_edge is not None:
        s = max(s, abs(away_win_edge))
    return s

LOCATIONS_PATH = os.path.join(os.path.dirname(__file__), "team_locations.json")


def load_locations():
    with open(LOCATIONS_PATH, encoding="utf-8") as f:
        return json.load(f)["teams"]


def haversine_miles(lat1, lon1, lat2, lon2):
    r = 3958.8  # earth radius, miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def annotate_distance(games, locations):
    for r in games:
        away, home = locations.get(r["away_team"]), locations.get(r["home_team"])
        r["_travel_miles"] = round(haversine_miles(away["lat"], away["lon"], home["lat"], home["lon"]), 0) if away and home else None
    return games


def run_geo_filter(games, team_game_index, name, pred, desc):
    cohort = [r for r in games if pred(r)]
    complement = [r for r in games if not pred(r)]
    cohort_stats, baseline_stats = outcomes(cohort), outcomes(complement)
    home_cohort_vol = stat_summary(cohort, team_game_index, "home")
    home_baseline_vol = stat_summary(complement, team_game_index, "home")
    away_cohort_vol = stat_summary(cohort, team_game_index, "away")
    away_baseline_vol = stat_summary(complement, team_game_index, "away")
    return {
        "filter": name, "description": desc,
        "cohort": cohort_stats, "baseline": baseline_stats,
        "over_under_edge_vs_baseline": edge(cohort_stats["over_rate"], baseline_stats["over_rate"]),
        "home_ats_edge_vs_baseline": edge(cohort_stats["home_cover_rate"], baseline_stats["home_cover_rate"]),
        "away_win_rate_edge_vs_baseline": edge(cohort_stats["away_win_rate"], baseline_stats["away_win_rate"]),
        "home_team_volume": {"cohort": home_cohort_vol, "baseline": home_baseline_vol,
                              "relative_edge": stat_edges(home_cohort_vol, home_baseline_vol)},
        "away_team_volume": {"cohort": away_cohort_vol, "baseline": away_baseline_vol,
                              "relative_edge": stat_edges(away_cohort_vol, away_baseline_vol)},
    }


def geo_filters(games, team_game_index):
    results = []
    results.append(run_geo_filter(
        games, team_game_index, "cross_country_travel",
        lambda r: (r.get("_travel_miles") or 0) >= 1500,
        "Away team traveling 1500+ miles"))
    results.append(run_geo_filter(
        games, team_game_index, "cross_country_short_week",
        lambda r: (r.get("_travel_miles") or 0) >= 1500 and (to_float(r.get("away_rest")) or 99) <= 4,
        "Away team traveling 1500+ miles on a short week (<=4 days rest)"))
    results.append(run_geo_filter(
        games, team_game_index, "denver_altitude_visitor",
        lambda r: r.get("home_team") == "DEN",
        "Visiting team at Denver's elevation (5,280ft)"))
    results.append(run_geo_filter(
        games, team_game_index, "denver_altitude_visitor_early_season",
        lambda r: r.get("home_team") == "DEN" and (to_float(r.get("week")) or 99) <= 6,
        "Visiting team at Denver's elevation, weeks 1-6 (before altitude acclimation claims apply most)"))
    return results


def bodyclock_analysis(games, locations, hour_min=None, hour_max=None, label="", description=""):
    """Per-team-appearance: does being the more-western team in a kickoff window
    [hour_min, hour_max) ET predict a better SU/ATS record than a flat 50%?

    Two claims this is used to test:
      - primetime (hour_min=20): West Coast teams have a circadian edge in night
        games — a real, published, widely-cited finding (Smith et al.)
      - early window (hour_max=13): the popular "West Coast team's body clock says
        it's 10am, so they underperform in early ET kickoffs" claim — the SAME
        published research found no significant effect here, contrary to what a lot
        of NFL content repeats. Worth checking against this fuller dataset rather
        than taking either claim on faith.
    """
    advantaged = []
    for r in games:
        gametime = r.get("gametime")
        if not gametime:
            continue
        try:
            hour = int(gametime.split(":")[0])
        except ValueError:
            continue
        if hour_min is not None and hour < hour_min:
            continue
        if hour_max is not None and hour >= hour_max:
            continue

        home, away = r.get("home_team"), r.get("away_team")
        home_loc, away_loc = locations.get(home), locations.get(away)
        if not home_loc or not away_loc:
            continue
        home_tz, away_tz = home_loc["tz_offset_from_et"], away_loc["tz_offset_from_et"]
        if home_tz == away_tz:
            continue  # no clock edge either way

        result = to_float(r.get("result"))  # home_score - away_score
        spread = to_float(r.get("spread_line"))
        if result is None:
            continue

        home_is_west = home_tz < away_tz
        adv_team, adv_side = (home, "home") if home_is_west else (away, "away")
        own_margin = result if adv_side == "home" else -result
        own_spread = spread if (adv_side == "home" and spread is not None) else (-spread if spread is not None else None)
        won = own_margin > 0
        covered = (own_margin > own_spread) if own_spread is not None else None
        advantaged.append({"team": adv_team, "won": won, "covered": covered, "margin": own_margin})

    # Baseline is a flat 50%: league-wide, every game has exactly one SU/ATS winner,
    # so the advantaged group's rate can be compared straight to a coin flip.
    n = len(advantaged)
    win_rate = round(sum(1 for a in advantaged if a["won"]) / n, 3) if n else None
    cover_candidates = [a for a in advantaged if a["covered"] is not None]
    cover_rate = round(sum(1 for a in cover_candidates if a["covered"]) / len(cover_candidates), 3) if cover_candidates else None
    avg_margin = round(sum(a["margin"] for a in advantaged) / n, 2) if n else None

    return {
        "analysis": label,
        "description": description,
        "n_games": n,
        "n_ats_decisions": len(cover_candidates),
        "win_rate": win_rate,
        "win_rate_edge_vs_50pct": round(win_rate - 0.5, 3) if win_rate is not None else None,
        "cover_rate": cover_rate,
        "cover_rate_edge_vs_50pct": round(cover_rate - 0.5, 3) if cover_rate is not None else None,
        "avg_margin": avg_margin,
        "caveat": "Compared to a flat 50% since every game has exactly one SU/ATS winner league-wide; a genuine edge should clear that baseline by a real margin, not just sit near it.",
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", action="store_true")
    ap.add_argument("--filter", help="cross_country_travel | cross_country_short_week | denver_altitude_visitor | denver_altitude_visitor_early_season")
    ap.add_argument("--bodyclock", action="store_true", help="run both West Coast body-clock analyses (primetime edge, early-kickoff 'myth')")
    ap.add_argument("--min-n", type=int, default=40)
    ap.add_argument("--min-edge", type=float, default=0.07)
    ap.add_argument("--min-stat-edge", type=float, default=0.12)
    args = ap.parse_args()

    locations = load_locations()
    games = annotate_distance(load_games(), locations)

    if args.bodyclock:
        primetime = bodyclock_analysis(
            games, locations, hour_min=20,
            label="bodyclock_primetime_edge",
            description="More-western team in an 8pm ET+ kickoff — own-perspective SU/ATS record")
        early = bodyclock_analysis(
            games, locations, hour_max=13,
            label="bodyclock_early_kickoff_myth_check",
            description="More-western team in a kickoff before 1pm ET (the popular '10am body clock' fade claim) — own-perspective SU/ATS record")
        print(json.dumps({"primetime": primetime, "early_kickoff": early}, indent=2))
        return

    team_game_index = load_team_game_stats()
    results = geo_filters(games, team_game_index)

    if args.filter:
        match = next((r for r in results if r["filter"] == args.filter), None)
        print(json.dumps(match or {"error": f"unknown filter {args.filter}"}, indent=2))
        return

    if args.scan:
        signals = [r for r in results if is_signal(r, args.min_n, args.min_edge, args.min_stat_edge)]
        signals.sort(key=strength, reverse=True)
        print(json.dumps({"scanned": len(results), "signals_found": len(signals), "signals": signals}, indent=2))
        return

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
