# NFL Weekly Market Report — pipeline runbook

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
  - `stats_player_week_<year>.csv` (release tag `stats_player`, one file per season) —
    every player's weekly stats (yards, targets, position, opponent) — powers form,
    primetime hit-rate, and defense-vs-position. **Not** the old combined
    `player_stats.csv`, which stopped updating in May 2025 and silently serves stale data.
  - Use `pipeline/prop_stats.py` (stdlib only, no pip install needed) rather than
    re-deriving this by hand each week:
    ```
    python3 pipeline/prop_stats.py --player "Puka Nacua" --opponent SF \
      --stat receiving_yards --line 79.5 --expect-team LA
    ```
    Returns L5 hit rate, primetime hit rate + sample size, season average, and the
    opponent's defense-vs-position rank (1 = allows the most to that position —
    the best matchup for the prop). `--stat` supports `receiving_yards`,
    `rushing_yards`, `passing_yards`, `receptions`. It caches the two source CSVs
    for ~20h so a week's worth of lookups only downloads each file once.
    **Always pass `--expect-team`** with whichever team you believe the player is
    currently on. Players change teams — a Week 4 2026 report put Kenneth Walker III
    and Isiah Pacheco on their *old* teams (both had already signed elsewhere in
    free agency), so the picks were tied to games neither of them actually played
    in. `--expect-team` turns that into a hard failure (the script errors out and
    reports the player's actual current team) instead of a silent bad pick. Treat
    that error as a stop sign, not something to retry past — re-derive who the
    player's team's actual current starter/lead option is before picking anyone
    for that game.
- Tracked source list (edit this list as leans/confidence in creators changes; each
  entry was checked for two things — real/established, and has genuinely public
  content, not just a paywalled teaser):
  - **Hold the Line** — podcast, X @HoldtheLinePod
  - **Dr. Locks MD** — Facebook "Dr Locks MD", Instagram @dr.locks.md, X @DrLocksMD
  - **Bet the Board** — podcast (X @BetTheBoardPod), hosted by Todd Fuhrman (former
    Caesars Sportsbook oddsmaker, FS1's lead gambling analyst on Fox Sports' Lock It
    In) and Payne (payneinsider.com). Free newsletter with additional best bets.
  - **Sean Koerner ("The Oddsmaker")** — Action Network's model-based picks, X
    @The_Oddsmaker. His on-air picks record is publicly tracked and openly
    published including losing stretches — a good sign this isn't a hype account.
    Use his free/public posts only; Action Network's deeper PRO content is paywalled.
  - **Bob Stoll (Dr. Bob Sports)** — drbobsports.com, X @DrBobSports. Handicapping
    since 1987, WSJ-featured, ESPN E:60 segment, syndicated widely; publicly
    transparent about his own record trending down in recent years, which is
    exactly the kind of source worth trusting more, not less.
  - **VSiN (Vegas Stats & Information Network)** — the closest thing here to an
    institutional source: a real Las Vegas broadcast network (SiriusXM channel,
    founded by Brent Musburger's family) staffed by actual Nevada oddsmakers
    (Jimmy Vaccaro, Vinny Magliulo, Chris Andrews). Free podcasts/shows at vsin.com.
  - **NFL Pickwatch** (nflpickwatch.com) — not a single creator; a free tool that
    already aggregates and scores ATS/O-U/moneyline picks from ESPN, CBS, PFF, and
    other mainstream media experts, with live consensus percentages. Treat this as
    a shortcut to mainstream-media consensus rather than one more individual voice
    to average in — it's already doing a version of what this whole pipeline does,
    just for institutional pundits instead of independent handicappers.
  - [add more here as they're found and verified — same two checks: real/established, genuinely public]
- Public betting-percentage signal: whatever is visible on Action Network's free
  public-betting page, plus any explicit "public is on X, I'm on Y" calls from tracked
  sources. Full split data is PRO-gated — do not attempt to bypass that paywall.
- Injuries: ESPN, NFL.com. Pregame weather forecast for outdoor stadiums (games.csv
  only has actual temp/wind for games already played): a free weather API.
- **Situational pattern engine** (`pipeline/situational_splits.py` +
  `pipeline/situations/*.json`) — for hand-curated, real-world cohorts that can't be
  derived from the schedule columns alone: "team debuting a new stadium," "coaching
  change," etc. See "Situational angles" below.
- **Fresh data every run:** `historical_screen.py`'s downloads never expire, so on
  a machine that has run before, delete `pipeline/.cache/games.csv` and the current
  season's `stats_player_week_<year>.csv` first (a cloud routine starts from a clean
  checkout, so this only bites local runs). Results, injuries and lines all change
  between drafts.
- **Historical screen** (`pipeline/historical_screen.py`) — a much broader, fully
  automatic scan of 42 structural cohorts (rest days, weather, spread size,
  divisional, weekday/slot, momentum, lookahead/trap spots, and compounds of those)
  across 1999-2026, run with `--scan` to surface only the ones that clear a real edge
  threshold. This is the primary tool for "strong signal" angles.
- **Travel & body-clock** (`pipeline/travel_and_clock.py` + `pipeline/team_locations.json`)
  — the geography-dependent angles historical_screen.py can't do on schedule columns
  alone: cross-country travel distance, Denver's altitude, and the "West Coast teams
  have a circadian edge in primetime" claim (real, and separately, the popular "fade
  them in early games" claim, which is not — see `--bodyclock`).
- See "Reading the screen/travel output" below before using either tool's numbers in
  a report — both are about finding real edges, not confirming a narrative someone
  already believes.

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
   sources independently land on the same side. Note which sources agreed. NFL
   Pickwatch counts as one source for this count (its own mainstream-consensus %
   is one data point, not a vote per underlying expert) — but when an independent
   handicapper lean is ALSO backed by Pickwatch's mainstream consensus, say so
   explicitly ("X and Y agree, and it's also the mainstream media consensus") —
   that's a meaningfully different, stronger claim than two independent voices
   agreeing with each other alone.

5. **Check public-money signal.** (If no real public-split data is available — Action
   Network's splits are PRO-only — replace the "Fade the Public" section with a
   "Line Moves Since <last publish>" section built from the odds you actually pulled,
   rather than a placeholder saying nothing was found.) Where a line hasn't moved despite lopsided public
   backing on one side, flag the other side as a "Fade the Public" candidate. Don't
   fabricate percentages you can't actually see — only report signal you pulled from
   a real source.

6. **Verify injuries at the source — before writing a single leg.** Fetch the raw
   NFL.com article "NFL Week N injury report: Player statuses for all 16 games" with
   `curl -sL -A "Mozilla/5.0 ..."`, strip the tags, and read each game's block
   (OUT / DOUBTFUL / QUESTIONABLE per team; "No injury designations" means healthy).
   Check every player who carries a prop or leg, and every starting QB. Drop any prop
   for a player listed at all, and don't back receivers whose starting QB is out.
   **Do not use WebFetch/WebSearch summaries for statuses** — on the Week 2 run a
   WebFetch summary put Derrick Henry on the Titans and Kenneth Walker on the
   Seahawks (stale assumptions, not the page), and Friday's published report still
   contained a receiver who was ruled out. Re-run this on the morning of publish,
   not just when the report is first drafted; also compare current lines against the
   ones in the last published version and call out real moves.

   **Pull context.** Injuries (especially Wed/Thu practice reports), weather forecast
   for outdoor games, and any relevant trend notes for the games in headline leans and
   key matchups. Historical team trends (ATS/O-U in primetime, by roof/surface) are
   derivable from `games.csv` the same way the player stats are.

7. **Check for a situational angle.** `python3 this_week.py` does the cross-referencing
   automatically now — it auto-detects the current week and reports which
   already-validated filters (from historical_screen.py and travel_and_clock.py) are
   actually triggered by real games this week. Use its output directly rather than
   eyeballing the slate against the filter list by hand. Only reach for
   `situational_splits.py` separately when something this week matches (or is worth
   adding as) a hand-curated cohort in `pipeline/situations/` — new stadium, coaching
   change, etc. — since those aren't schedule-derivable and this_week.py can't see them.
   Weigh a finding internally by its real sample size and caveats — but see
   "Report voice" below before writing any of that into the report itself; readers
   get the conclusion, not the methodology. A coin-flip/null result still shapes what
   you leave OUT of the report (it's a reason NOT to pitch a popular narrative as a
   lean, e.g. "letdown spot" or "revenge game" — neither clears a real edge across
   25+ years of data). Don't discard a null result internally and go hunting for a
   different cohort that "worked" instead — just don't publish a stats appendix
   about it either; the reader only needs to not be sold a bet that doesn't hold up.

8. **Flag games to avoid.** Games with no source consensus, high line volatility
   this week, or an unresolved injury situation. State why.

9. **Write the report.** Follow the exact section structure and HTML/CSS in
   `public/reports/2026-week-05.html` — that file is the current template (supersedes
   the older `2026-week-01-sample.html`, which predates the tabbed layout below).
   Save the new file as `public/reports/<slug>.html` (slug format: `YYYY-week-NN`).
   Keep both `<div data-subscribe-widget></div>` mounts (near the top, and again near
   the bottom before `footer-nav`) and the `<script src="/subscribe-widget.js">`
   tag before `</body>` — every report page needs its own subscribe CTA, not just
   the homepage. Cover
   every game on the slate in the matchup writeup (spread, total, and any notable
   prop), in readable sports-column prose — but the "Best Bets" leg list only ever
   contains **High Confidence** and **Confident** legs (see tiers below). A game
   with nothing that clears Confident still gets covered in the writeup; it just
   doesn't contribute a leg to the list.

   **Tabbed layout (as of Week 5).** The tabs go right after the lede, since Best
   Bets/Full Slate/Multi Suggestion are the longest, most look-up-able content —
   collapsing them is the whole point. "Fade the Public"/line-move color, "Games to
   Avoid", and "Last Week's Track Record" stay as plain, always-visible sections
   *below* the tabs, same relative order as before. Three tabs, in this order —
   Best Bets, Full Slate, Multi Suggestion (`.tabs`/`.tab-panel` in `style.css`; copy
   the small inline `<script>` at the bottom of the Week 5 file verbatim into each
   new report for the click-to-switch behavior):
   - **Best Bets** — now a `<table>`, not a `<ul>`: columns Pick / Market / Tier / Why.
     One row per leg, same tier rules as before.
   - **Full Slate** — the per-game accordion, with one addition (as of Week 5): the
     `<summary>` (the always-visible collapsed row, before any click) now has a
     second line, `.summary-calls`, below the existing matchup/lines row (wrap that
     existing row in `.summary-top` — see the CSS). It states, for every game, one
     line each on:
     - **Side** — an explicit take on spread *or* moneyline, not just the raw lines
       (which still show in `.summary-top`): either a specific pick, bolded (e.g.
       `Side: **Tennessee +7.5** (spread)`), or plainly `Side: No lean` when nothing
       cleared the bar. Don't skip this for games with no pick — a reader scanning
       the tab should see every game got a real look, not silence.
     - **Total** — same idea, `Total: **Over 54.5**` or `Total: No lean`.
     - **Props** — a compact list of this game's prop picks by name and alt line
       only (`Woody Marks O12.5 rush`), no reasoning — the reasoning stays inside
       the expanded body, same as before. This is what makes the tab scannable
       without opening every game: Side/Total/Props at a glance, click only for
       the *why*.
     Keep the expanded body exactly as before (prose + per-prop `leg-why` boxes).
   - **Multi Suggestion** — new. Pick 3-5 legs from this week's Best Bets with the
     single strongest conviction — prefer legs with the cleanest hit rate (5-of-5 over
     4-of-5), a validated situational signal rather than just a volume/favorite
     narrative, and variety across games (don't bundle three legs from one game; a
     single bad beat in that game sinks the whole multi for no added diversification).
     This is an editorial judgment call each week, not a script's output — explain
     *why* each leg made the cut in one line. **Do not compute or display combined
     odds/payout** — the point is "these are our most confident reads," not a specific
     price to hit. If the week doesn't have at least 3 legs worth bundling this way
     (e.g. a week with no spread/total legs and only thin props), say so plainly
     instead of forcing weak legs in just to fill the tab.

   **Every game gets an alt-line player prop where the data supports it** (not every
   game will). Pull the player's trailing game log via `prop_stats.py` and set the line
   at roughly **75% of his median over the last five games** (fall back to 68%, then
   60%), rounded down to a .5. Keep the prop only if he cleared that line in **at
   least 4 of the last 5**; otherwise skip the player — volatile players (e.g. a
   receiver going 82/71/13/0/79) produce junk lines like "over 10.5" and shouldn't be
   forced in. Minimum line 9.5. If an external projection puts his usual line below the
   computed alt (a hot streak inflating the median — e.g. Henry, median 128, projected
   ~88), cap the alt under the projection so it is genuinely the *safer* number.
   State the hit count in plain language ("cleared in each of his last five games") —
   a concrete fact for the reader, unlike sample sizes/edge percentages. Skip a player
   if the current-season-plus-last-season sample is thin. Alt lines are always set
   below the usual line, so tell the reader to look for the closest rung on their
   book's ladder. Over = green pill, Under = red pill (`label over` / `label under`);
   team chips (`team-chip team-XXX`) mark a team-side market or identify a leg's team;
   the favourite in each game's line uses `team-text team-XXX`.

   **Report voice — read this before writing a word of reader-facing copy:**
   - No raw numbers from the pipeline appear in the report: no sample sizes, no
     edge percentages, no L5/primetime hit-rate fractions, no tool or script names
     (`historical_screen.py`, `--scan`, etc.), no "n=". Translate every one of
     those into a plain-English reason instead — "the trend has been reliable,"
     "this matchup favors the run," "the market's moved toward them" — the same
     way a sports column would explain a pick, not a data appendix.
   - This is a *filter*, not a rewrite of the underlying judgment: only apply this
     rule to what you SHOW; the confidence tiering underneath still has to be
     honestly earned from steps 1-8, not vibes.

   **Confidence tiers for the Best Bets list:**
   - A **spread or total leg needs a statistical signal for that specific market** —
     an ATS or Over/Under edge that cleared the tool's threshold. A *volume* signal
     (e.g. "home favorites run ~14% more") only supports **props**, never a side or a
     total: on the Week 2 refresh, "Eagles −7", "49ers −13.5", "Over 50.5" and a
     Broncos lean all had no such backing and were removed from the list (the one
     relevant ATS signal actually leaned the other way, just under the bar).
   - **High Confidence** — a validated signal that cleared its threshold AND
     independent corroboration: 2+ separate public analysts or published metrics
     (e.g. Covers, DK Network, SportsLine, DVOA/PFF grades, usage data) pointing the
     same way, **checked against the raw page text**, not a search summary.
   - **Confident** — clears ONE of those two bars (a validated signal alone, or
     corroboration alone) plus the 4-of-5 alt-line check for props.
   - **Anything weaker does not go on the list.** A single opinion with no backing,
     or a signal that didn't clear its own threshold, is not a leg — it can appear as
     color in the matchup writeup, never as something to bet. It is fine — and
     honest — for a week to have no spread/total legs at all.
   - **Matchup claims** ("soft run defense") must be corroborated by an external
     measure before they appear in copy. `prop_stats.py`'s defense-vs-position rank
     is a yards-allowed *volume* stat (now a trailing 17-game window; it used to be
     current-season-only, i.e. a single game in Week 2) and disagrees with efficiency
     metrics (Tennessee ranked 21st on it but 28th in run-defense DVOA). Treat it as
     a hint, not a claim.
   - **Moneyline is a third game-market type, alongside spread and total — check it
     every week, don't default to spread out of habit.** A moneyline (take-the-team,
     no points) leg needs its own, different kind of signal: a genuine straight-up
     win-rate edge, not just "this team is favored" (that's already priced into the
     moneyline odds, so it's not an edge, it's just chalk). `historical_screen.py`
     exposes `home_ml_edge_vs_baseline` on every filter's output (via `--filter
     <name>`, not `--scan`) specifically for this check — but it is **deliberately
     excluded from `--scan`/`this_week.py`'s automatic signal list**, because for any
     cohort that's basically defined by "being a favorite" or "being an underdog"
     (`home_favorite_any`, `home_big_favorite`, `home_underdog`, `home_big_underdog`),
     that edge is tautological — of course favorites win straight-up more than the
     whole-league baseline, that's what favorite means, and the market already knows
     it. A moneyline pick only earns a spot on Best Bets when the edge is a genuine
     surprise relative to what the spread/odds alone would predict, which in practice
     means: the spread is close (±3 or so, where ATS and SU are nearly the same bet)
     **and** you already have a validated situational signal pointing that direction —
     in that case the same signal can back both the spread AND the moneyline, say so
     explicitly. Don't invent a moneyline lean from a lopsided-favorite cohort just to
     have one. Worked example from Week 5: `away_lookahead_trap` backs Tennessee
     +7.5 ATS (a real, checked edge), but `home_ml_edge_vs_baseline` on that same
     filter shows the big underdog in that exact trap spot still loses straight-up
     roughly three games out of four — so that signal supports the spread, not
     Tennessee on the moneyline. Checking and finding nothing is a fine, honest
     outcome; say so rather than silently never mentioning moneylines at all.

10. **Update the archive index.** Prepend an entry to `reports/index.json` with
    `slug`, `date`, `week`, `title`, `summary`.

11. **Commit and push** to the repo's default branch — this triggers a Vercel
    redeploy, so the new report and archive entry go live automatically.

12. **Send the email.**
    ```
    python3 pipeline/send_report.py --html public/reports/<slug>.html \
      --subject "<week's headline lean in one line>" --send
    ```
    Needs `RESEND_API_KEY`, `RESEND_AUDIENCE_ID`, `RESEND_FROM_EMAIL` (a verified
    Resend sending domain — `reports.haveaplan.xyz`, sending as
    `NFL Weekly Market Report <weekly@reports.haveaplan.xyz>`) as env vars. Without `--send` it only creates a draft in the Resend
    dashboard and sends nothing — useful for a final look before the real send.
    Its requests need an explicit `User-Agent` header or Cloudflare 403s them
    (seen from Python's default urllib UA) — already handled in the script, but
    worth knowing if a similar direct-API call gets added elsewhere.

13. **Grade last week.** Before generating this week's report, check final scores
    for last week's picks (verify against an actual box score, not a recap summary)
    and record win/loss in two places:
    - This week's report, in the "Last Week's Track Record" prose section (plain
      English, same report-voice rules as everything else).
    - `reports/results.json`, which feeds the standalone running-results page
      (`public/results.html`, via `api/results.js`) — append one entry per graded
      leg: `{"week": "Week 4", "type": "prop" | "spread" | "total" | "moneyline",
      "pick": "<plain description>", "result": "win" | "loss" | "push" | "void",
      "actual": "<the real number, e.g. '27 receiving yards' or final score for a
      spread/total/moneyline leg>"}`. Always include `actual` for a graded prop (the
      owner specifically wants to see what a losing — or winning — prop actually
      came in at, not just win/loss) and for any graded game-line pick once those
      exist; pull it from a real box score the same way step 13's grading does, not
      a rounded recap figure. Use `"void"` (not `"loss"`) for a pick that turns out to have been wrong at the
      data level rather than the handicapping level — e.g. the Walker/Pacheco
      roster mistake from Week 4 — and say so in the report prose too; a void
      doesn't count toward the win rate either way, but it also shouldn't be
      silently dropped from the history. `results.html` reports player-prop results
      and game-level results (spread/total/moneyline) as separate running totals,
      per the split the project owner asked for — don't merge them into one number.

## Reading the screen/travel output

This section is about how to *decide* what's real — internal reasoning that feeds
the confidence tiers above. None of the numbers, filter names, or sample sizes
mentioned here belong in the report itself; see "Report voice" under step 9.

The closing spread and total are a genuinely efficient market — no structural filter
in either tool moves the Over/Under or ATS rate against the closing line by more than
~7-12 points even at the extremes (`historical_screen.py --scan` defaults: min sample
60, min edge 0.07 rate-points / 0.12 relative). Don't manufacture a bigger "beat the
closing line" edge than that; it isn't there, and claiming otherwise would be
publishing a false signal.

The real, usable, consistently large signal in this data is **game-script volume**:
how much a team runs vs. passes shifts hard and predictably with spread size and total
size — a 10+ point home favorite runs about 16% more rushing yards than baseline,
a big home underdog's rushing production drops by a similar margin while the team
they're trailing gains it. That's not a market-inefficiency claim, it's just how
football is played, and it's exactly what a rushing/passing yardage prop needs.
**Lead with volume edges for prop leans; treat OU/ATS edges from either tool as
context, not a standalone pick.**

A few filters are genuinely strong enough to lead a section with on their own —
`away_lookahead_trap` (a team that was a big favorite last week and is a much bigger
underdog this week: the opponent they're trapped looking past covers ~12 points more
than baseline, n=102) and the primetime half of `--bodyclock` (the West Coast
circadian-edge claim: +4 win-rate points, +1.9 cover-rate points over a flat 50%,
n=534 — real, though more modest than the "70% ATS" version of this stat that
circulates). The early-kickoff half of `--bodyclock` is the useful negative: the
popular "fade West Coast teams in early ET games" claim shows an exact **0.0** cover-rate
edge in this data (n=74) — a real, sourced counter to something a lot of NFL content
repeats as fact.

Don't lean on any one filter as the headline every week just because it produced a
notable number once — including ones a subscriber or the report's own author
suggested testing. Treat every filter the same way: report what the data shows,
weighted by its own sample size, and rotate through whichever ones are actually live
for that week's slate rather than always reaching for a favorite.

A filter that scans and finds nothing is a real result, not a bug (`home_revenge` /
`away_revenge` / `home_off_loss` / `home_off_win` are examples of this — large
samples, no edge). Don't treat a null result as evidence the filter idea was bad;
it's just what the data says this time. Mention nulls in passing where relevant
rather than building a section around any single one of them — a report that spent
its "unique angle" space debunking one specific narrative every week would get
repetitive fast, and there are 40+ other filters that do find something.

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

Most "narrative" cohorts (short week, revenge games, coming off a win/loss, extreme
weather) turned out to be fully derivable from games.csv and now live as filters in
`historical_screen.py` instead — reserve `situations/*.json` for things that genuinely
need outside knowledge to identify (new stadium, coaching change, key injury return,
a franchise relocation). Before hand-curating a new cohort, check whether it can
instead be expressed as a predicate on existing columns (or a two-line enrichment
pass like `_home_revenge`) and added to `historical_screen.py` — it scales to way
more instances and doesn't risk an incomplete/mis-curated list.

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
