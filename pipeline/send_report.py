#!/usr/bin/env python3
"""
Sends the weekly report to the Resend audience.

Safety default: creates the broadcast as a DRAFT only (Resend's `send: false`).
Nothing goes to subscribers unless --send is passed explicitly. This script does
not decide on its own whether unattended sending is OK — that's a one-time call the
project owner makes when the recurring schedule is set up, not something to assume
here.

Requires env vars: RESEND_API_KEY, RESEND_AUDIENCE_ID, RESEND_FROM_EMAIL
(e.g. "NFL Weekly <reports@notify.thissunday.xyz>" — must be on a verified
Resend sending domain).

Usage:
  python3 send_report.py --html public/reports/2026-week-02.html --subject "Week 2: Chiefs -2.5, Chase over, and a trap game in Tennessee"
  python3 send_report.py --html ... --subject ... --send     # actually sends
"""

import argparse
import json
import os
import urllib.error
import urllib.request


def resend_request(method, path, api_key, body=None):
    req = urllib.request.Request(
        f"https://api.resend.com{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            # Cloudflare (in front of Resend's API) blocks urllib's default
            # User-Agent with a bare 403 (error 1010) — any real UA string works.
            "User-Agent": "nfl-weekly-report/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {"raw_error": raw.decode(errors="replace")}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--html", required=True, help="path to the report's HTML file")
    ap.add_argument("--subject", required=True)
    ap.add_argument("--send", action="store_true", help="actually send — omit to create a draft only")
    args = ap.parse_args()

    api_key = os.environ.get("RESEND_API_KEY")
    audience_id = os.environ.get("RESEND_AUDIENCE_ID")
    from_email = os.environ.get("RESEND_FROM_EMAIL")
    missing = [name for name, v in [("RESEND_API_KEY", api_key), ("RESEND_AUDIENCE_ID", audience_id), ("RESEND_FROM_EMAIL", from_email)] if not v]
    if missing:
        raise SystemExit(f"Missing env vars: {', '.join(missing)}")

    with open(args.html, encoding="utf-8") as f:
        html = f.read()

    status, body = resend_request("POST", "/broadcasts", api_key, {
        "audience_id": audience_id,
        "from": from_email,
        "subject": args.subject,
        "html": html,
        "send": args.send,
    })

    if status >= 300:
        raise SystemExit(f"Resend error {status}: {body}")

    if args.send:
        print(f"SENT: broadcast {body['id']}")
    else:
        print(f"DRAFT created (not sent): broadcast {body['id']}")
        print("Re-run with --send to actually deliver it, or send/discard it from the Resend dashboard.")


if __name__ == "__main__":
    main()
