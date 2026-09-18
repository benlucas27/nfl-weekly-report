#!/usr/bin/env python3
"""
Broad, rule-based historical screener over nflverse-data (1999-2026, free, no key).
Unlike situational_splits.py (which needs a hand-curated instance list for cohorts
that aren't derivable from the schedule alone, like "new stadium"), every filter here
is a structural condition on games.csv columns — rest days, divisional, roof/surface,
weather, spread, weekday/slot — so dozens of angles can be scanned automatically.

Every cohort is compared against its own complement (all OTHER games), not a flat 50%,
because league-wide over/under and ATS rates drift a little on their own. A filter only
counts as a "signal" when both are true:
  - sample size >= --min-n (default 60)
  - |cohort rate - baseline rate| >= --min-edge (default 0.07, i.e. 7 points)

Usage:
  python3 historical_screen.py --scan                      # every filter, signals only
  python3 historical_screen.py --scan --min-n 40 --min-edge 0.05
  python3 historical_screen.py --filter short_week_home     # one filter, full detail
  python3 historical_screen.py --list                       # show all filter names

Metrics per filter: Over/Under rate (actual total vs. closing total_line), Home ATS
cover rate (actual home margin vs. closing spread_line; spread_line > 0 means the home
team was favored, so "home covers" means result > spread_line) — these move very little
versus a sharp closing line, because Vegas already prices rest/weather/divisional
familiarity into the number. The bigger, more usable edges tend to be in **volume**:
each cohort also reports each side's average rush attempts/yards and pass
attempts/yards per team-game vs. the baseline, which is where real game-script effects
(a big favorite running more, a big underdog throwing more) actually show up — useful
for player-prop leans even when the closing line itself barely moves.
"""

import argparse
import csv
import json
import math
import os
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime

GAMES_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv"
# The combined player_stats.csv release stopped being updated in May 2025 -- it
# loads fine and looks plausible but silently serves 2022-2024 data as "current."
# stats_player_week_<year>.csv (one file per season) is the maintained replacement.
STATS_WEEK_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{year}.csv"
STATS_FIRST_YEAR = 1999
CACHE_DIR = os.path.join(os.path.dirname(__file__), ".cache")
STAT_COLUMNS = ["carries", "rushing_yards", "attempts", "passing_yards"]


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
        rows = list(csv.DictReader(f))
    return [r for r in rows if r.get("game_type") == "REG"]


def load_team_game_stats():
    """(season, week, team) -> {carries, rushing_yards, attempts, passing_yards} team totals.
    Concatenates every season's stats_player_week_<year>.csv rather than the stale
    combined file, so this now genuinely covers through the current season."""
    from datetime import date
    index = defaultdict(lambda: defaultdict(float))
    for year in range(STATS_FIRST_YEAR, date.today().year + 1):
        url = STATS_WEEK_URL.format(year=year)
        try:
            path = _cached_download(url, f"stats_player_week_{year}.csv")
        except urllib.error.HTTPError:
            continue  # future season file may not exist yet
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                team = r.get("team", r.get("recent_team"))
                key = (r.get("season"), r.get("week"), team)
                for col in STAT_COLUMNS:
                    v = to_float(r.get(col))
                    if v is not None:
                        index[key][col] += v
    return index


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def month_of(row):
    try:
        return datetime.strptime(row["gameday"], "%Y-%m-%d").month
    except (ValueError, KeyError):
        return None


def enrich_games(games):
    """Adds several team-perspective flags in place, computed chronologically
    (crossing season boundaries so Week 1 is covered using the prior season's finale):
      _home_prev_result / _away_prev_result  'W'/'L'/'T' in the immediately preceding game
      _away_back_to_back_road                this team's previous game was also on the road
      _home_lookahead_trap / _away_lookahead_trap
        this team was a meaningful favorite (own-perspective spread >= 7) this week,
        AND is a meaningfully bigger underdog next week (own-perspective spread drops
        by >=10) — the classic "focused on next week's tougher opponent" trap-game setup.
    """
    per_team = defaultdict(list)
    for r in games:
        hs, aws = to_float(r.get("home_score")), to_float(r.get("away_score"))
        per_team[r["home_team"]].append((r["season"], r["week"], r, "home", hs, aws))
        per_team[r["away_team"]].append((r["season"], r["week"], r, "away", hs, aws))

    for team, appearances in per_team.items():
        appearances.sort(key=lambda a: (int(a[0]), int(a[1])))
        prev_result = None
        prev_side = None
        for season, week, row, side, hs, aws in appearances:
            key = "_home_prev_result" if side == "home" else "_away_prev_result"
            row[key] = prev_result
            if side == "away":
                row["_away_back_to_back_road"] = (prev_side == "away")
            prev_side = side
            if hs is None or aws is None:
                prev_result = None  # game not yet played/scored
                continue
            team_score, opp_score = (hs, aws) if side == "home" else (aws, hs)
            prev_result = "W" if team_score > opp_score else ("L" if team_score < opp_score else "T")

        # Lookahead trap: compare this game's own-perspective spread to the very next
        # game's, within the same appearances list (already chronological).
        for i in range(len(appearances) - 1):
            season, week, row, side, hs, aws = appearances[i]
            _, _, next_row, next_side, _, _ = appearances[i + 1]
            this_spread = _spread(row)
            next_spread = _spread(next_row)
            if this_spread is None or next_spread is None:
                continue
            own_this = this_spread if side == "home" else -this_spread
            own_next = next_spread if next_side == "home" else -next_spread
            is_trap = own_this >= 7 and (own_this - own_next) >= 10
            row["_home_lookahead_trap" if side == "home" else "_away_lookahead_trap"] = is_trap

    # Revenge-game flag: did this exact matchup's most recent previous meeting (in
    # either venue) go against the team that's home in THIS game?
    games_sorted = sorted(games, key=lambda r: (int(r["season"]), int(r["week"])))
    last_winner = {}
    for r in games_sorted:
        home, away = r["home_team"], r["away_team"]
        pair = frozenset((home, away))
        prev_winner = last_winner.get(pair)
        r["_home_revenge"] = prev_winner is not None and prev_winner == away
        r["_away_revenge"] = prev_winner is not None and prev_winner == home
        hs, aws = to_float(r.get("home_score")), to_float(r.get("away_score"))
        if hs is not None and aws is not None:
            last_winner[pair] = home if hs > aws else (away if aws > hs else "T")
    return games


# --- Filter registry -------------------------------------------------------
# Each filter is (description, predicate(row) -> bool). Predicates must only use
# columns present on every row; missing/NA values should just fail the predicate.

def _spread(r): return to_float(r.get("spread_line"))
def _rest_home(r): return to_float(r.get("home_rest"))
def _rest_away(r): return to_float(r.get("away_rest"))
def _temp(r): return to_float(r.get("temp"))
def _wind(r): return to_float(r.get("wind"))

FILTERS = {
    "short_week_home": ("Home team on a short week (<=4 days rest)",
        lambda r: (_rest_home(r) or 99) <= 4),
    "short_week_away": ("Away team on a short week (<=4 days rest)",
        lambda r: (_rest_away(r) or 99) <= 4),
    "bye_week_home": ("Home team off a bye (>=13 days rest)",
        lambda r: (_rest_home(r) or 0) >= 13),
    "bye_week_away": ("Away team off a bye (>=13 days rest)",
        lambda r: (_rest_away(r) or 0) >= 13),
    "rest_advantage_home": ("Home team has >=3 more rest days than the away team",
        lambda r: (_rest_home(r) or 0) - (_rest_away(r) or 0) >= 3),
    "rest_advantage_away": ("Away team has >=3 more rest days than the home team",
        lambda r: (_rest_away(r) or 0) - (_rest_home(r) or 0) >= 3),
    "divisional": ("Divisional matchup",
        lambda r: r.get("div_game") == "1"),
    "dome_or_closed": ("Played under a dome/closed roof",
        lambda r: r.get("roof") in ("dome", "closed")),
    "outdoor_cold": ("Outdoors and <=32F",
        lambda r: r.get("roof") == "outdoors" and (_temp(r) is not None) and _temp(r) <= 32),
    "outdoor_hot": ("Outdoors and >=85F",
        lambda r: r.get("roof") == "outdoors" and (_temp(r) is not None) and _temp(r) >= 85),
    "high_wind": ("Wind >=15mph",
        lambda r: (_wind(r) or 0) >= 15),
    "grass": ("Grass surface",
        lambda r: "grass" in (r.get("surface") or "").lower()),
    "turf": ("Artificial turf surface",
        lambda r: "turf" in (r.get("surface") or "").lower() or "astro" in (r.get("surface") or "").lower()),
    "home_underdog": ("Home team is the underdog (spread_line < 0)",
        lambda r: (_spread(r) or 0) < 0),
    "home_big_favorite": ("Home team favored by 10+",
        lambda r: (_spread(r) or -99) >= 10),
    "home_big_underdog": ("Home team getting 7+ points",
        lambda r: (_spread(r) or 99) <= -7),
    "pick_em": ("Within a field goal either way (|spread| <= 3)",
        lambda r: abs(_spread(r) or 99) <= 3),
    "thursday": ("Thursday game",
        lambda r: r.get("weekday") == "Thursday"),
    "monday_night": ("Monday game",
        lambda r: r.get("weekday") == "Monday"),
    "sunday_night": ("Sunday game with a night kickoff (>=18:00)",
        lambda r: r.get("weekday") == "Sunday" and r.get("gametime") and int(r["gametime"].split(":")[0]) >= 18),
    "early_season": ("Weeks 1-3",
        lambda r: to_float(r.get("week")) is not None and to_float(r.get("week")) <= 3),
    "late_season_cold": ("December/January",
        lambda r: month_of(r) in (12, 1)),
    "shootout_line": ("Total line set at 50+",
        lambda r: (to_float(r.get("total_line")) or 0) >= 50),
    "defensive_line": ("Total line set at 38 or under",
        lambda r: (to_float(r.get("total_line")) or 99) <= 38),
    "international": ("Neutral-site / international game",
        lambda r: r.get("location") not in (None, "", "Home")),
    "home_favorite_any": ("Home team favored by any margin",
        lambda r: (_spread(r) or -99) > 0),
    "primetime_any": ("Thursday, Sunday night, or Monday night",
        lambda r: r.get("weekday") in ("Thursday", "Monday")
                  or (r.get("weekday") == "Sunday" and r.get("gametime") and int(r["gametime"].split(":")[0]) >= 18)),
    "first_half_season": ("Weeks 1-9",
        lambda r: (to_float(r.get("week")) or 99) <= 9),
    "second_half_season": ("Weeks 10+",
        lambda r: (to_float(r.get("week")) or 0) >= 10),
    "home_off_loss": ("Home team lost its immediately preceding game",
        lambda r: r.get("_home_prev_result") == "L"),
    "home_off_win": ("Home team won its immediately preceding game",
        lambda r: r.get("_home_prev_result") == "W"),
    "away_off_loss": ("Away team lost its immediately preceding game",
        lambda r: r.get("_away_prev_result") == "L"),
    "away_off_win": ("Away team won its immediately preceding game",
        lambda r: r.get("_away_prev_result") == "W"),
    "home_off_win_favorite": ("Home team won last time out and is favored again now (possible letdown setup)",
        lambda r: r.get("_home_prev_result") == "W" and (_spread(r) or -99) > 0),
    "home_revenge": ("Home team lost the most recent previous meeting vs. this exact opponent",
        lambda r: r.get("_home_revenge") is True),
    "away_revenge": ("Away team lost the most recent previous meeting vs. this exact opponent",
        lambda r: r.get("_away_revenge") is True),
    "divisional_short_week": ("Divisional matchup on a short week for either side",
        lambda r: r.get("div_game") == "1" and ((_rest_home(r) or 99) <= 4 or (_rest_away(r) or 99) <= 4)),
    "cold_and_dog": ("Outdoors, <=40F, and the home team is an underdog",
        lambda r: r.get("roof") == "outdoors" and (_temp(r) is not None) and _temp(r) <= 40 and (_spread(r) or 0) < 0),
    "wind_and_favorite": ("Wind >=15mph and the home team is favored (run-heavy script expected twice over)",
        lambda r: (_wind(r) or 0) >= 15 and (_spread(r) or -99) > 0),
    "back_to_back_road": ("Away team's previous game was also on the road",
        lambda r: r.get("_away_back_to_back_road") is True),
    "home_lookahead_trap": ("Home team: big favorite this week, much bigger underdog next week",
        lambda r: r.get("_home_lookahead_trap") is True),
    "away_lookahead_trap": ("Away team: big favorite this week, much bigger underdog next week",
        lambda r: r.get("_away_lookahead_trap") is True),
}


def outcomes(rows):
    """Over/under, ATS, and straight-up record for a set of game rows."""
    over = under = push_ou = 0
    home_cover = away_cover = push_ats = 0
    home_win = away_win = tie = 0
    for r in rows:
        line, total = to_float(r.get("total_line")), to_float(r.get("total"))
        if line is not None and total is not None:
            if total > line: over += 1
            elif total < line: under += 1
            else: push_ou += 1
        spread, result = to_float(r.get("spread_line")), to_float(r.get("result"))
        if spread is not None and result is not None:
            if result > spread: home_cover += 1
            elif result < spread: away_cover += 1
            else: push_ats += 1
        if result is not None:
            if result > 0: home_win += 1
            elif result < 0: away_win += 1
            else: tie += 1
    return {
        "n": len(rows),
        "over": over, "under": under, "push_ou": push_ou,
        "over_rate": round(over / (over + under), 3) if (over + under) else None,
        "home_cover": home_cover, "away_cover": away_cover, "push_ats": push_ats,
        "home_cover_rate": round(home_cover / (home_cover + away_cover), 3) if (home_cover + away_cover) else None,
        "away_cover_rate": round(away_cover / (home_cover + away_cover), 3) if (home_cover + away_cover) else None,
        "home_win_rate": round(home_win / (home_win + away_win), 3) if (home_win + away_win) else None,
        "away_win_rate": round(away_win / (home_win + away_win), 3) if (home_win + away_win) else None,
    }


def edge(cohort_rate, baseline_rate):
    if cohort_rate is None or baseline_rate is None:
        return None
    return round(cohort_rate - baseline_rate, 3)


def stat_summary(rows, team_game_index, side):
    """Average team-game volume/yardage for `side` ('home' or 'away') across rows."""
    team_col = "home_team" if side == "home" else "away_team"
    sums = defaultdict(float)
    n = 0
    for r in rows:
        key = (r.get("season"), r.get("week"), r.get(team_col))
        game_stats = team_game_index.get(key)
        if not game_stats:
            continue
        n += 1
        for col in STAT_COLUMNS:
            sums[col] += game_stats.get(col, 0.0)
    return {"n": n, **{col: round(sums[col] / n, 1) if n else None for col in STAT_COLUMNS}}


def relative_edge(cohort_avg, baseline_avg):
    if cohort_avg is None or baseline_avg is None or baseline_avg == 0:
        return None
    return round((cohort_avg - baseline_avg) / baseline_avg, 3)


def stat_edges(cohort_summary, baseline_summary):
    return {col: relative_edge(cohort_summary.get(col), baseline_summary.get(col)) for col in STAT_COLUMNS}


def stderr(n, p=0.5):
    return math.sqrt(p * (1 - p) / n) if n else None


def run_filter(games, name, team_game_index):
    desc, pred = FILTERS[name]
    cohort = [r for r in games if pred(r)]
    complement = [r for r in games if not pred(r)]
    cohort_stats = outcomes(cohort)
    baseline_stats = outcomes(complement)

    ou_edge = edge(cohort_stats["over_rate"], baseline_stats["over_rate"])
    ats_edge = edge(cohort_stats["home_cover_rate"], baseline_stats["home_cover_rate"])

    home_cohort_vol = stat_summary(cohort, team_game_index, "home")
    home_baseline_vol = stat_summary(complement, team_game_index, "home")
    away_cohort_vol = stat_summary(cohort, team_game_index, "away")
    away_baseline_vol = stat_summary(complement, team_game_index, "away")

    return {
        "filter": name,
        "description": desc,
        "cohort": cohort_stats,
        "baseline": baseline_stats,
        "over_under_edge_vs_baseline": ou_edge,
        "home_ats_edge_vs_baseline": ats_edge,
        "over_under_stderr": round(stderr(cohort_stats["n"]), 3) if cohort_stats["n"] else None,
        "home_ats_stderr": round(stderr(cohort_stats["n"]), 3) if cohort_stats["n"] else None,
        "home_team_volume": {"cohort": home_cohort_vol, "baseline": home_baseline_vol,
                              "relative_edge": stat_edges(home_cohort_vol, home_baseline_vol)},
        "away_team_volume": {"cohort": away_cohort_vol, "baseline": away_baseline_vol,
                              "relative_edge": stat_edges(away_cohort_vol, away_baseline_vol)},
    }


def is_signal(result, min_n, min_edge, min_stat_edge):
    n = result["cohort"]["n"]
    if n < min_n:
        return False
    for edge_key in ("over_under_edge_vs_baseline", "home_ats_edge_vs_baseline"):
        e = result[edge_key]
        if e is not None and abs(e) >= min_edge:
            return True
    for side in ("home_team_volume", "away_team_volume"):
        for e in result[side]["relative_edge"].values():
            if e is not None and abs(e) >= min_stat_edge:
                return True
    return False


def strength(result):
    edges = [abs(e) for e in (result["over_under_edge_vs_baseline"], result["home_ats_edge_vs_baseline"]) if e is not None]
    # scale relative volume edges (fractions like 0.15) onto the same rough footing as
    # rate-point edges so a big game-script signal can outrank a marginal ATS wobble
    for side in ("home_team_volume", "away_team_volume"):
        edges += [abs(e) for e in result[side]["relative_edge"].values() if e is not None]
    return max(edges) if edges else 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", action="store_true", help="run every filter, print only signals")
    ap.add_argument("--filter", help="run one filter by name (see --list)")
    ap.add_argument("--list", action="store_true", help="list available filter names")
    ap.add_argument("--min-n", type=int, default=60)
    ap.add_argument("--min-edge", type=float, default=0.07, help="min OU/ATS rate-point edge")
    ap.add_argument("--min-stat-edge", type=float, default=0.12, help="min relative volume edge (0.12 = 12%%)")
    args = ap.parse_args()

    if args.list:
        for name, (desc, _) in FILTERS.items():
            print(f"{name}: {desc}")
        return

    games = enrich_games(load_games())
    team_game_index = load_team_game_stats()

    if args.filter:
        print(json.dumps(run_filter(games, args.filter, team_game_index), indent=2))
        return

    results = [run_filter(games, name, team_game_index) for name in FILTERS]
    signals = [r for r in results if is_signal(r, args.min_n, args.min_edge, args.min_stat_edge)]
    signals.sort(key=strength, reverse=True)

    print(json.dumps({
        "scanned": len(results),
        "min_n": args.min_n,
        "min_edge": args.min_edge,
        "min_stat_edge": args.min_stat_edge,
        "signals_found": len(signals),
        "signals": signals,
    }, indent=2))


if __name__ == "__main__":
    main()
