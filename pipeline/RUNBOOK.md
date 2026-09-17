# NFL Weekly Consensus Report — pipeline runbook

This is what the scheduled agent does each week. It runs as a cloud scheduled Claude
agent (not a hardcoded scraper) so it can use WebSearch/WebFetch live each week instead
of relying on brittle scrapers against social platforms.

**Trigger:** weekly, Thursday morning AEST (after Wednesday US injury reports, before
Thursday Night Football kicks off).

## Inputs

- `ODDS_API_KEY` — The Odds API free tier: spreads, moneylines, totals for the week's
  NFL slate. (Player props are NOT on the free tier — see step 3.)
- **[nflverse-data](https://github.com/nflverse/nflverse-data)** — free, no key,
  updated automatically. This is the historical stats backbone:
  - `games.csv` — full schedule incl. `weekday`/`gametime` (primetime splits) and
    historical `spread_line`/`total_line`/odds/`roof`/`surface`/`temp`/`wind`
  - `player_stats.csv` — every player's weekly stats back to 1999 (yards, targets,
    position, opponent) — powers form, primetime hit-rate, and defense-vs-position
  - Use `pipeline/prop_stats.py` (stdlib only, no pip install needed) rather than
    re-deriving this by hand each week:
    ```
    python3 pipeline/prop_stats.py --player "Puka Nacua" --opponent SF \
      --stat receiving_yards --line 79.5
    ```
    Returns L5 hit rate, primetime hit rate + sample size, season average, and the
    opponent's defense-vs-position rank (1 = allows the most to that position —
    the best matchup for the prop). `--stat` supports `receiving_yards`,
    `rushing_yards`, `passing_yards`, `receptions`. It caches the two source CSVs
    for ~20h so a week's worth of lookups only downloads each file once.
- Tracked source list (edit this list as leans/confidence in creators changes):
  - Hold the Line (podcast + @HoldtheLinePod)
  - Dr. Locks MD (Facebook "Dr Locks MD", Instagram @dr.locks.md, X @DrLocksMD)
  - [add more here once confirmed — aim for 3-4+ independent voices]
- Public betting-percentage signal: whatever is visible on Action Network's free
  public-betting page, plus any explicit "public is on X, I'm on Y" calls from tracked
  sources. Full split data is PRO-gated — do not attempt to bypass that paywall.
- Injuries: ESPN, NFL.com. Pregame weather forecast for outdoor stadiums (games.csv
  only has actual temp/wind for games already played): a free weather API.
- **Situational pattern engine** (`pipeline/situational_splits.py` +
  `pipeline/situations/*.json`) — for "unique angle" trends that aren't tied to one
  player's game log: cohorts like "team debuting a new stadium," joined against
  games.csv/player_stats.csv to get over/under record and lead-rusher performance
  vs. their own season baseline for that cohort. See "Situational angles" below.

## Steps

1. **Pull the week's lines.** Call The Odds API for NFL spreads/moneylines/totals.
   Snapshot the current line for every game.

2. **Gather source picks.** For each tracked source, WebSearch/WebFetch their most
   recent public content (this week's episode/post). Extract any explicit picks:
   team, market type (spread/ML/total/prop), side, and their stated reasoning.
   Player prop leans come from here, not from a paid odds feed, since props aren't
   on the free API tier.

3. **Back each prop pick with stats.** For every player prop mentioned by a tracked
   source (and any other prop lines worth covering), run `prop_stats.py` for that
   player/stat/line. Report the L5 hit rate, primetime hit rate, and opponent
   defense-vs-position rank alongside the pick. If the stats *contradict* a source's
   pick, say so — don't quietly drop the conflict.

4. **Find consensus.** A market becomes a "Headline Lean" only when 2+ tracked
   sources independently land on the same side. Note which sources agreed.

5. **Check public-money signal.** Where a line hasn't moved despite lopsided public
   backing on one side, flag the other side as a "Fade the Public" candidate. Don't
   fabricate percentages you can't actually see — only report signal you pulled from
   a real source.

6. **Pull context.** Injuries (especially Wed/Thu practice reports), weather forecast
   for outdoor games, and any relevant trend notes for the games in headline leans and
   key matchups. Historical team trends (ATS/O-U in primetime, by roof/surface) are
   derivable from `games.csv` the same way the player stats are.

7. **Check for a situational angle.** Scan this week's slate for anything matching an
   existing entry in `pipeline/situations/` (new-stadium debut, short week, revenge
   game, etc. — see below) or worth adding as a new one. Run
   `situational_splits.py` and include the finding only if the sample is honestly
   reported with its size and caveats — a coin-flip result ("over rate 0.50") is
   itself a useful, honest thing to publish; don't discard a null result and go
   looking for a different cohort that "worked."

8. **Flag games to avoid.** Games with no source consensus, high line volatility
   this week, or an unresolved injury situation. State why.

9. **Write the report.** Follow the exact section structure and HTML/CSS in
   `public/reports/2026-week-01-sample.html` — that file is the template. Save the
   new file as `public/reports/<slug>.html` (slug format: `YYYY-week-NN`).

10. **Update the archive index.** Prepend an entry to `reports/index.json` with
    `slug`, `date`, `week`, `title`, `summary`.

11. **Commit and push** to the repo's default branch — this triggers a Vercel
    redeploy, so the new report and archive entry go live automatically.

12. **Send the email.** Use the Resend API to send a campaign to the audience
    (`RESEND_AUDIENCE_ID`) built from the same report content — a condensed version
    with headline leans up top and a link to the full report on the site.

13. **Grade last week.** Before generating this week's report, check final scores
    for last week's headline leans and record win/loss in the track-record section
    (mirrors the history-tracking pattern from the NRL report pipeline).

## Situational angles — adding a new one

`pipeline/situations/new_stadium_debut.json` is the template. Each file is a curated,
hand-verified list of (team, season) instances for a real, well-defined cohort — the
tool can't discover these on its own, since they usually depend on something not in
the data (a stadium being newly *built* rather than renamed, a coaching change, a
franchise relocation). To add one:

1. Research and hand-verify the instance list (team/season, plus a `notes` field for
   any confound — bye weeks, COVID, a concurrent roster overhaul, etc.). Don't invent
   instances; if the list can't be verified against real sources, don't ship it.
2. Save it as `pipeline/situations/<situation_name>.json`, same shape as the
   new-stadium one.
3. `situational_splits.py --situation <situation_name>` works immediately — it joins
   on games.csv/player_stats.csv generically, no code changes needed for a new cohort
   that's just "some team's home games in some season(s)."
4. If the cohort needs a different join (e.g. "the away team, not the home team" or
   "a specific week, not the opener") that's a small, explicit change to
   `situational_splits.py` — don't bend an unrelated cohort into the existing shape
   just to avoid touching the script.

Ideas worth curating over time: short-week road games, revenge games (lost to this
opponent last meeting), letdown spots (off a primetime win, home dog the next week),
extreme-weather games, long-layoff-after-bye games.

## Things this deliberately does NOT do

- Does not scrape paywalled content (Action Network PRO splits, any subscriber-only
  creator content). If a tracked source's picks aren't publicly visible that week,
  skip them for that market rather than guessing.
- Does not fabricate a consensus. If nothing clears the 2-source bar for a given
  game, that game just doesn't get a headline lean.
- Does not cherry-pick situational cohorts until one "hits." A null/coin-flip result
  from `situational_splits.py` is worth publishing as-is — it tells subscribers a
  popular narrative doesn't actually hold up, which is useful information.
- Does not give staking/bankroll advice — leans and reasoning only.
