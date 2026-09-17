# NFL Weekly Consensus Report

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
  debuts trend" (`pipeline/situational_splits.py`); and a 39-filter automatic screen
  (rest days, weather, spread size, momentum, divisional, and compounds of those) that
  surfaces only the cohorts with a real edge over their own baseline
  (`pipeline/historical_screen.py --scan`).
- A weekly cloud-scheduled Claude agent runs the actual report pipeline and pushes
  the result to this repo, which auto-redeploys on Vercel.

## Setup

1. **Resend**
   - Create an Audience in your Resend dashboard, copy its ID.
   - Grab your API key from Resend settings.

2. **The Odds API**
   - Sign up free at the-odds-api.com, grab the API key.

3. **Vercel**
   - Import this repo as a new Vercel project (framework preset: "Other").
   - Add environment variables: `RESEND_API_KEY`, `RESEND_AUDIENCE_ID`, `ODDS_API_KEY`.
   - Deploy — landing page at `/`, archive at `/archive.html`.

4. **Local dev**
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
  historical_screen.py    39-filter automatic scan for real structural edges
  situational_splits.py   hand-curated cohort trends (e.g. new-stadium debuts)
  situations/*.json       curated instance lists that situational_splits.py joins against
```

## Pipeline tools

All three scripts are pure Python stdlib (no `pip install`) and pull straight from
nflverse-data's free CSV releases, caching them in `pipeline/.cache/` for the day:

```bash
python3 pipeline/prop_stats.py --player "Puka Nacua" --opponent SF \
  --stat receiving_yards --line 79.5

python3 pipeline/historical_screen.py --scan
python3 pipeline/historical_screen.py --filter home_big_favorite

python3 pipeline/situational_splits.py --situation new_stadium_debut --scope season
```

`historical_screen.py --scan` only prints filters that clear a real edge over their
own baseline (default: 60+ games, 7+ rate-points on Over/Under or ATS, or 12%+ on
rush/pass volume) — see [pipeline/RUNBOOK.md](pipeline/RUNBOOK.md#reading-historical_screenpy-output)
for why the real edge lives in game-script volume, not the closing line itself.

## Send day

Thursday morning AEST — after Wednesday (US) injury reports land, before Thursday
Night Football kicks off. Covers the full week's slate including TNF.
