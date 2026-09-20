#!/usr/bin/env python3
"""
Turns a published report page into an email-safe HTML body.

The site pages depend on an external stylesheet, JavaScript and <details> dropdowns —
none of which survive an email client — so the email is a short version: headline,
intro, the Best Bets legs (inline-styled, table layout), and a button to the full
report. Includes Resend's unsubscribe placeholder so broadcasts carry a working
unsubscribe link.

Usage:
  python3 report_to_email.py public/reports/2026-week2-full.html --out /tmp/week2-email.html
  python3 send_report.py --html /tmp/week2-email.html --subject "..."        # draft only
"""

import argparse
import html
import os
import re
import sys
from html.parser import HTMLParser

SITE = "https://nfl-weekly-report.vercel.app"
VOID = {"meta", "link", "br", "img", "input", "hr"}


class ReportParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []          # (tag, target|None)
        self.tag = self.h1 = self.lede = self.note = ""
        self.h2s = []
        self.legs = []
        self.cur = None
        self.in_legs = False
        self.seen_best_h2 = False
        self.note_done = False

    def _target(self):
        for _, t in reversed(self.stack):
            if t:
                return t
        return None

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            return
        cls = set((dict(attrs).get("class") or "").split())
        target = None
        if tag == "span" and "tag" in cls: target = "tag"
        elif tag == "h1": target = "h1"
        elif tag == "h2": target = "h2"
        elif tag == "p" and "lede" in cls: target = "lede"
        elif tag == "p" and "section-note" in cls and self.seen_best_h2 and not self.note_done:
            target = "note"
        elif tag == "ul" and "legs" in cls:
            self.in_legs = True
        elif self.in_legs and tag == "li":
            self.cur = {"name": "", "chip": None, "chip_class": None, "labels": [], "why": ""}
        elif self.cur is not None:
            if tag == "span" and "leg-name" in cls: target = "name"
            elif tag == "span" and "team-chip" in cls:
                target = "chip"
                self.cur["chip_class"] = next((c for c in cls if c.startswith("team-") and c != "team-chip"), None)
            elif tag == "span" and "label" in cls:
                target = "label"
                self.cur["labels"].append({"kinds": sorted(cls - {"label"}), "text": ""})
            elif tag == "div" and "leg-why" in cls: target = "why"
        self.stack.append((tag, target))

    def handle_endtag(self, tag):
        if tag in VOID or not self.stack:
            return
        while self.stack:
            t, target = self.stack.pop()
            if t == tag:
                if target == "note":
                    self.note_done = True
                break
        if tag == "ul":
            self.in_legs = False
        if tag == "li" and self.cur is not None:
            self.legs.append(self.cur)
            self.cur = None

    def handle_data(self, data):
        target = self._target()
        if not target:
            return
        text = re.sub(r"\s+", " ", data)
        if target == "tag": self.tag += text
        elif target == "h1": self.h1 += text
        elif target == "lede": self.lede += text
        elif target == "note": self.note += text
        elif target == "h2":
            self.h2s.append(text.strip())
            if "best bets" in text.lower():
                self.seen_best_h2 = True
        elif self.cur is not None:
            if target == "name": self.cur["name"] += text
            elif target == "chip": self.cur["chip"] = (self.cur["chip"] or "") + text
            elif target == "label": self.cur["labels"][-1]["text"] += text
            elif target == "why": self.cur["why"] += text


def team_colors():
    path = os.path.join(os.path.dirname(__file__), "..", "public", "team-colors.css")
    colors = {}
    try:
        for m in re.finditer(r"\.team-([A-Z]+)\s*\{\s*--team:\s*(#[0-9A-Fa-f]{6})", open(path).read()):
            colors[m.group(1)] = m.group(2)
    except OSError:
        pass
    return colors


def pill(kinds, text):
    text = html.escape(text.strip())
    if "over" in kinds:
        style = "color:#1a7a3c;background:#eaf5ee;border:1px solid #1a7a3c;"
    elif "under" in kinds:
        style = "color:#b8342a;background:#fbeceb;border:1px solid #b8342a;"
    elif "high" in kinds:
        style = "color:#ffffff;background:#0a0a0a;border:1px solid #0a0a0a;"
    else:
        style = "color:#0a0a0a;background:#ffffff;border:1px solid #0a0a0a;"
    return (f'<span style="display:inline-block;{style}font-size:11px;letter-spacing:0.06em;'
            f'text-transform:uppercase;padding:2px 7px;border-radius:3px;margin-right:6px;">{text}</span>')


def build(path, url):
    p = ReportParser()
    p.feed(open(path, encoding="utf-8").read())
    colors = team_colors()
    legs_html = []
    for leg in p.legs:
        chip = ""
        if leg["chip"]:
            abbr = (leg["chip_class"] or "").replace("team-", "")
            col = colors.get(abbr, "#0a0a0a")
            chip = (f'<span style="display:inline-block;border:1.5px solid {col};color:{col};font-weight:700;'
                    f'font-size:12px;padding:0 6px;border-radius:3px;margin-right:6px;">{html.escape(leg["chip"].strip())}</span>')
        pills = "".join(pill(l["kinds"], l["text"]) for l in leg["labels"])
        legs_html.append(f'''<tr><td style="padding:16px 0;border-bottom:1px solid #e4e4e4;">
<div style="font-size:16px;font-weight:700;color:#0a0a0a;line-height:1.35;">{chip}{html.escape(leg["name"].strip())}</div>
<div style="margin:8px 0 6px;">{pills}</div>
<div style="font-size:14px;color:#555555;line-height:1.5;">{html.escape(leg["why"].strip())}</div>
</td></tr>''')

    return f'''<!doctype html>
<html><body style="margin:0;padding:0;background:#f4f4f4;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f4;"><tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#ffffff;border-radius:8px;">
<tr><td style="padding:32px 28px 8px;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#0a0a0a;">
<div style="font-size:11px;letter-spacing:0.08em;text-transform:uppercase;color:#777777;">{html.escape(p.tag.strip())}</div>
<div style="font-family:Georgia,serif;font-size:28px;line-height:1.2;margin:10px 0 12px;">{html.escape(p.h1.strip())}</div>
<div style="font-size:15px;line-height:1.55;color:#555555;">{html.escape(p.lede.strip())}</div>
<div style="font-family:Georgia,serif;font-size:20px;margin:28px 0 4px;">This Week&#39;s Best Bets</div>
<div style="font-size:13px;color:#777777;line-height:1.5;">{html.escape(p.note.strip())}</div>
</td></tr>
<tr><td style="padding:0 28px;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(legs_html)}</table>
</td></tr>
<tr><td align="center" style="padding:28px;">
<a href="{url}" style="display:inline-block;background:#0a0a0a;color:#ffffff;text-decoration:none;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-weight:600;font-size:15px;padding:14px 26px;border-radius:6px;">Read the full report &rarr; every game, every prop</a>
</td></tr>
<tr><td style="padding:0 28px 28px;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:12px;color:#888888;line-height:1.5;">
Betting involves risk &mdash; these are leans from public data, not guarantees. Please bet responsibly.<br>
<a href="{{{{{{RESEND_UNSUBSCRIBE_URL}}}}}}" style="color:#888888;">Unsubscribe</a>
</td></tr>
</table></td></tr></table></body></html>
'''


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report")
    ap.add_argument("--out", required=True)
    ap.add_argument("--url", help="public URL of the report (default: derived from the filename)")
    a = ap.parse_args()
    url = a.url or f"{SITE}/reports/{os.path.basename(a.report)}"
    out = build(a.report, url)
    open(a.out, "w", encoding="utf-8").write(out)
    print(f"wrote {a.out} ({len(out)} bytes) -> links to {url}")


if __name__ == "__main__":
    main()
