# NFL Weekly Consensus Report — pipeline runbook

This is what the scheduled agent does each week. It runs as a cloud scheduled Claude
agent (not a hardcoded scraper) so it can use WebSearch/WebFetch live each week instead
of relying on brittle scrapers against social platforms.

**Trigger:** weekly, Thursday morning AEST (after Wednesday US injury reports, before
Thursday Night Football kicks off).

## Inputs

- `ODDS_API_KEY` — The Odds API free tier: spreads, moneylines, totals for the week's
  NFL slate. (Player props are NOT on the free tier — see step 2.)
- Tracked source list (edit this list as leans/confidence in creators changes):
  - Hold the Line (podcast + @HoldtheLinePod)
  - Dr. Locks MD (Facebook "Dr Locks MD", Instagram @dr.locks.md, X @DrLocksMD)
  - [add more here once confirmed — aim for 3-4+ independent voices]
- Public betting-percentage signal: whatever is visible on Action Network's free
  public-betting page, plus any explicit "public is on X, I'm on Y" calls from tracked
  sources. Full split data is PRO-gated — do not attempt to bypass that paywall.
- Injuries/weather: ESPN, NFL.com, a free weather API for outdoor stadiums.

## Steps

1. **Pull the week's lines.** Call The Odds API for NFL spreads/moneylines/totals.
   Snapshot the current line for every game.

2. **Gather source picks.** For each tracked source, WebSearch/WebFetch their most
   recent public content (this week's episode/post). Extract any explicit picks:
   team, market type (spread/ML/total/prop), side, and their stated reasoning.
   Player prop leans come from here, not from a paid odds feed, since props aren't
   on the free API tier.

3. **Find consensus.** A market becomes a "Headline Lean" only when 2+ tracked
   sources independently land on the same side. Note which sources agreed.

4. **Check public-money signal.** Where a line hasn't moved despite lopsided public
   backing on one side, flag the other side as a "Fade the Public" candidate. Don't
   fabricate percentages you can't actually see — only report signal you pulled from
   a real source.

5. **Pull context.** Injuries (especially Wed/Thu practice reports), weather for
   outdoor games, and any relevant trend notes for the games in headline leans and
   key matchups.

6. **Flag games to avoid.** Games with no source consensus, high line volatility
   this week, or an unresolved injury situation. State why.

7. **Write the report.** Follow the exact section structure and HTML/CSS in
   `public/reports/2026-week-01-sample.html` — that file is the template. Save the
   new file as `public/reports/<slug>.html` (slug format: `YYYY-week-NN`).

8. **Update the archive index.** Prepend an entry to `reports/index.json` with
   `slug`, `date`, `week`, `title`, `summary`.

9. **Commit and push** to the repo's default branch — this triggers a Vercel
   redeploy, so the new report and archive entry go live automatically.

10. **Send the email.** Use the Resend API to send a campaign to the audience
    (`RESEND_AUDIENCE_ID`) built from the same report content — a condensed version
    with headline leans up top and a link to the full report on the site.

11. **Grade last week.** Before generating this week's report, check final scores
    for last week's headline leans and record win/loss in the track-record section
    (mirrors the history-tracking pattern from the NRL report pipeline).

## Things this deliberately does NOT do

- Does not scrape paywalled content (Action Network PRO splits, any subscriber-only
  creator content). If a tracked source's picks aren't publicly visible that week,
  skip them for that market rather than guessing.
- Does not fabricate a consensus. If nothing clears the 2-source bar for a given
  game, that game just doesn't get a headline lean.
- Does not give staking/bankroll advice — leans and reasoning only.
