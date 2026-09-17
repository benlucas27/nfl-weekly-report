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
  RUNBOOK.md            what the weekly scheduled agent does, step by step
```

## Send day

Thursday morning AEST — after Wednesday (US) injury reports land, before Thursday
Night Football kicks off. Covers the full week's slate including TNF.
