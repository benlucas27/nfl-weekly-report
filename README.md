# NFL Weekly Market Report

Signup landing page + archive for a weekly NFL betting markets report: cross-referenced
leans from tracked betting content sources, plus fade-the-public spots and games to
avoid. See [pipeline/RUNBOOK.md](pipeline/RUNBOOK.md) for how the weekly report itself
gets generated and sent.

## Stack

- Static site (`public/`) + two Vercel serverless functions (`api/`) — no framework,
  zero-config Vercel deploy.
- [Resend](https://resend.com) — free tier (3,000 emails/mo, 100/day) for the
  subscriber audience and the weekly send.
- [The Odds API](https://the-odds-api.com) — free tier for spreads/moneylines/totals.
  Player props aren't on the free tier; prop leans come from tracked sources instead
  (see the runbook).
- [nflverse-data](https://github.com/nflverse/nflverse-data) — free, no key, historical
  play-by-play/schedule data back to 1999. Backs every prop pick with real form,
  primetime, and opponent-defense splits (`pipeline/prop_stats.py`); a curated-cohort
  tool for research questions that need outside knowledge, like "how do new-stadium
  debuts trend" (`pipeline/situational_splits.py`); a 42-filter automatic screen (rest
  days, weather, spread size, momentum, divisional, lookahead/trap spots, and compounds
  of those) that surfaces only cohorts with a real edge over their own baseline
  (`pipeline/historical_screen.py --scan`); and a travel/timezone module for
  cross-country distance, Denver altitude, and the West Coast body-clock effect
  (`pipeline/travel_and_clock.py`).
- A weekly cloud-scheduled Claude agent runs the actual report pipeline and pushes
  the result to this repo, which auto-redeploys on Vercel.

## Setup

Status as of Sept 2026: Resend account, Audience, API key, sending domain
(`notify.thissunday.xyz`), and Odds API key are all live and verified working.
What's left:

1. **Vercel** — import this repo at [vercel.com/new](https://vercel.com/new)
   (framework preset: "Other"), add environment variables `RESEND_API_KEY`,
   `RESEND_AUDIENCE_ID`, `ODDS_API_KEY`, deploy. Landing page at `/`, archive at
   `/archive.html`. In progress as of this commit.
2. **The weekly scheduled agent** — attempted, blocked: the cloud routines system
   doesn't have access to this GitHub repo yet (403 on creation). Needs the repo
   added to whatever GitHub App/connector Claude Code's cloud routines use, plus
   `RESEND_API_KEY`/`RESEND_AUDIENCE_ID`/`RESEND_FROM_EMAIL`/`ODDS_API_KEY` set on
   the routine's cloud environment (no local `.env.local` access there). Configured
   for Thursday 8am AEST, draft-only (no `--send`) for the first few weeks per the
   owner's request — ready to retry once access is granted.
3. ~~More tracked sources~~ — done. 7 total now: Hold the Line, Dr. Locks MD, Bet
   the Board (Todd Fuhrman), Sean Koerner/Action Network, Bob Stoll/Dr. Bob Sports,
   VSiN, and NFL Pickwatch (a free mainstream-media consensus aggregator, not an
   individual voice — see `pipeline/RUNBOOK.md` for how it's weighted differently).

Local dev for the site itself:
```bash
npm i -g vercel   # if you don't have it
vercel dev
```

## Structure

```
public/
  index.html         landing page + signup form
  archive.html        list of past reports
  reports/<slug>.html individual report pages (one per week)
  style.css
api/
  subscribe.js         POST -> adds email to Resend audience
  reports.js            GET  -> reads reports/index.json
reports/
  index.json            archive metadata, newest first
pipeline/
  RUNBOOK.md             what the weekly scheduled agent does, step by step
  prop_stats.py           per-player prop stats: L5/primetime hit rate, opp defense rank
  historical_screen.py    42-filter automatic scan for real structural edges
  travel_and_clock.py     cross-country travel, Denver altitude, West Coast body clock
  team_locations.json     hand-compiled lat/lon + timezone per team (travel_and_clock.py input)
  this_week.py            cross-references the REAL current slate against known signals
  send_report.py          sends the week's report via Resend (draft-only unless --send)
  situational_splits.py   hand-curated cohort trends (e.g. new-stadium debuts)
  situations/*.json       curated instance lists that situational_splits.py joins against
```

## Pipeline tools

All scripts are pure Python stdlib (no `pip install`) and pull straight from
nflverse-data's free CSV releases, caching them in `pipeline/.cache/` for the day:

```bash
python3 pipeline/prop_stats.py --player "Puka Nacua" --opponent SF \
  --stat receiving_yards --line 79.5

python3 pipeline/historical_screen.py --scan
python3 pipeline/historical_screen.py --filter home_big_favorite

python3 pipeline/travel_and_clock.py --scan
python3 pipeline/travel_and_clock.py --bodyclock

python3 pipeline/this_week.py                    # what's actually live this week

python3 pipeline/situational_splits.py --situation new_stadium_debut --scope season

python3 pipeline/send_report.py --html public/reports/<slug>.html \
  --subject "..." [--send]                       # draft-only without --send
```

`--scan` on either screen only prints filters that clear a real edge over their own
baseline (default: 40-60+ games, 7+ rate-points on Over/Under or ATS, or 12%+ on
rush/pass volume) — see [pipeline/RUNBOOK.md](pipeline/RUNBOOK.md#reading-the-screentravel-output)
for why the real edge lives in game-script volume, not the closing line itself, and
for what these tools found (and didn't) as of Sept 2026.

## Send day

Thursday morning AEST — after Wednesday (US) injury reports land, before Thursday
Night Football kicks off. Covers the full week's slate including TNF.
