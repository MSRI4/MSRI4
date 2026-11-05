#!/usr/bin/env python3
"""Generate .NET-purple GitHub profile cards.

Writes assets/stats.svg and assets/languages.svg using the GitHub GraphQL API.
Runs inside GitHub Actions with the built-in GITHUB_TOKEN. Standard library only.

Local run:
    GITHUB_TOKEN=<token> GH_USERNAME=<you> python3 scripts/generate_cards.py
Placeholder cards (no network):
    python3 scripts/generate_cards.py --placeholder
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.request
from html import escape
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
USERNAME = os.environ.get("GH_USERNAME") or os.environ.get("GITHUB_REPOSITORY_OWNER", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
OUT_DIR = Path(os.environ.get("OUT_DIR", "assets"))
TOP_LANGS = 6
# Comma-separated languages to hide, e.g. "HTML,CSS" (ASP.NET templates inflate these)
EXCLUDE_LANGS = {s.strip().lower() for s in os.environ.get("EXCLUDE_LANGS", "").split(",") if s.strip()}

THEME = {
    "bg": "#120C26",
    "border": "#2E2260",
    "title": "#C9B8FF",
    "text": "#E6E0FF",
    "muted": "#9A90C0",
    "icon": "#9B7BFF",
    "track": "#2A1F4D",
    "bars": ["#512BD4", "#7C4DFF", "#9B7BFF", "#B39DFF", "#CDBDFF", "#E4DAFF"],
}
FONT = "'Segoe UI', Ubuntu, 'Helvetica Neue', Inter, Arial, sans-serif"
W, H = 420, 200

# ── GitHub API ────────────────────────────────────────────────────────────────
API = "https://api.github.com/graphql"

USER_QUERY = """
query($login: String!) {
  user(login: $login) {
    name
    login
    pullRequests { totalCount }
    issues { totalCount }
    contributionsCollection {
      totalCommitContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

REPO_QUERY = """
query($login: String!, $after: String) {
  user(login: $login) {
    repositories(first: 100, after: $after, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name } }
        }
      }
    }
  }
}
"""


def gql(query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        API,
        data=body,
        headers={
            "Authorization": f"bearer {TOKEN}",
            "Content-Type": "application/json",
            "User-Agent": "profile-cards-generator",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise RuntimeError(json.dumps(payload["errors"], indent=2))
    return payload["data"]


def fetch(login: str) -> dict:
    user = gql(USER_QUERY, {"login": login})["user"]
    if user is None:
        raise RuntimeError(f"GitHub user '{login}' not found")

    repos, after = [], None
    while True:
        page = gql(REPO_QUERY, {"login": login, "after": after})["user"]["repositories"]
        repos.extend(page["nodes"])
        public_repos = page["totalCount"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]

    return {"user": user, "repos": repos, "public_repos": public_repos}


# ── Data shaping ──────────────────────────────────────────────────────────────
def streaks(days: list[dict]) -> tuple[int, int, int, int]:
    """Return (current, longest, active_days, total_days) from calendar days."""
    counts = [d["contributionCount"] for d in sorted(days, key=lambda d: d["date"])]
    longest = run = 0
    for c in counts:
        run = run + 1 if c > 0 else 0
        longest = max(longest, run)

    i = len(counts) - 1
    if i >= 0 and counts[i] == 0:  # today may not have contributions yet
        i -= 1
    current = 0
    while i >= 0 and counts[i] > 0:
        current += 1
        i -= 1

    return current, longest, sum(1 for c in counts if c > 0), len(counts)


def summarize(data: dict, login: str) -> dict:
    user, repos = data["user"], data["repos"]
    cc = user["contributionsCollection"]
    days = [d for w in cc["contributionCalendar"]["weeks"] for d in w["contributionDays"]]
    current, longest, active, total_days = streaks(days)

    sizes: dict[str, int] = {}
    for repo in repos:
        if repo["name"].lower() == login.lower():  # skip this profile repo itself
            continue
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name.lower() in EXCLUDE_LANGS:
                continue
            sizes[name] = sizes.get(name, 0) + edge["size"]

    top = sorted(sizes.items(), key=lambda kv: kv[1], reverse=True)[:TOP_LANGS]
    top_total = sum(s for _, s in top) or 1

    return {
        "name": user["name"] or user["login"],
        "stars": sum(r["stargazerCount"] for r in repos),
        "commits": cc["totalCommitContributions"],
        "prs": user["pullRequests"]["totalCount"],
        "issues": user["issues"]["totalCount"],
        "repos": data["public_repos"],
        "contributions": cc["contributionCalendar"]["totalContributions"],
        "current": current,
        "longest": longest,
        "active": active,
        "total_days": total_days or 365,
        "langs": [(n, s / top_total * 100) for n, s in top],
    }


# ── SVG helpers ───────────────────────────────────────────────────────────────
def k(n: int) -> str:
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def star_points(cx: float, cy: float, r_out: float, r_in: float) -> str:
    pts = []
    for i in range(10):
        r = r_out if i % 2 == 0 else r_in
        a = math.radians(-90 + i * 36)
        pts.append(f"{cx + r * math.cos(a):.2f},{cy + r * math.sin(a):.2f}")
    return " ".join(pts)


ICONS = {
    "star": f'<polygon points="{star_points(8, 8.5, 7.5, 3.3)}" fill="none" stroke-linejoin="round"/>',
    "commit": '<circle cx="8" cy="8" r="3.2"/><path d="M0.5 8h4.3M11.2 8h4.3"/>',
    "pr": '<circle cx="4" cy="3.2" r="2"/><circle cx="4" cy="12.8" r="2"/><circle cx="12" cy="12.8" r="2"/>'
    '<path d="M4 5.2v5.6M12 10.8V6.5a3 3 0 0 0-3-3H7.2M8.8 1.8 7.1 3.5l1.7 1.7"/>',
    "issue": '<circle cx="8" cy="8" r="6.6"/><circle cx="8" cy="8" r="1.4" fill="currentColor"/>',
    "repo": '<rect x="2.5" y="1.5" width="11" height="13" rx="1.6"/><path d="M5.6 1.5v13"/>',
    "bolt": '<polygon points="9.2,0.8 3,9 7.4,9 6.6,15.2 13,6.8 8.6,6.8" fill="currentColor" stroke="none"/>',
}


def icon(name: str, x: float, y: float) -> str:
    return (
        f'<g transform="translate({x},{y})" fill="none" stroke="currentColor" stroke-width="1.4" '
        f'stroke-linecap="round" style="color:{THEME["icon"]}">{ICONS[name]}</g>'
    )


def card(title: str, body: str, extra_css: str = "") -> str:
    t = THEME
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(title)}">
  <title>{escape(title)}</title>
  <style>
    text {{ font-family: {FONT}; }}
    .title {{ font-size: 17px; font-weight: 700; fill: {t["title"]}; }}
    .label {{ font-size: 13.5px; fill: {t["muted"]}; }}
    .value {{ font-size: 13.5px; font-weight: 700; fill: {t["text"]}; }}
    .fade {{ animation: fade 0.6s ease-out backwards; }}
    @keyframes fade {{ from {{ opacity: 0; transform: translateX(-6px); }} }}{extra_css}
  </style>
  <rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" fill="{t["bg"]}" stroke="{t["border"]}"/>
  <text x="25" y="36" class="title">{escape(title)}</text>
{body}
</svg>
"""


def stats_svg(s: dict) -> str:
    rows = [
        ("star", "Total stars", k(s["stars"])),
        ("commit", "Commits (12 mo)", k(s["commits"])),
        ("pr", "Pull requests", k(s["prs"])),
        ("issue", "Issues", k(s["issues"])),
        ("repo", "Public repos", k(s["repos"])),
        ("bolt", "Streak (now / best)", f'{s["current"]} / {s["longest"]}'),
    ]
    body = []
    for i, (ic, label, value) in enumerate(rows):
        y = 66 + i * 23
        body.append(
            f'  <g class="fade" style="animation-delay:{150 + i * 120}ms">'
            f'{icon(ic, 25, y - 12)}'
            f'<text x="50" y="{y}" class="label">{label}</text>'
            f'<text x="262" y="{y}" class="value" text-anchor="end">{value}</text></g>'
        )

    cx, cy, r = 338, 106, 44
    circ = 2 * math.pi * r
    frac = min(1.0, s["active"] / s["total_days"]) if s["total_days"] else 0
    offset = circ * (1 - frac)
    body.append(f"""  <defs>
    <linearGradient id="ring" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#512BD4"/><stop offset="1" stop-color="#C9B8FF"/>
    </linearGradient>
  </defs>
  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{THEME["track"]}" stroke-width="9"/>
  <circle class="ring" cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="url(#ring)" stroke-width="9"
          stroke-linecap="round" stroke-dasharray="{circ:.2f}" stroke-dashoffset="{offset:.2f}"
          transform="rotate(-90 {cx} {cy})"/>
  <text x="{cx}" y="{cy + 5}" text-anchor="middle" style="font-size:24px;font-weight:800;fill:{THEME["text"]}">{k(s["contributions"])}</text>
  <text x="{cx}" y="{cy + 19}" text-anchor="middle" style="font-size:10px;fill:{THEME["muted"]}">contributions</text>
  <text x="{cx}" y="{cy + 74}" text-anchor="middle" class="label" style="font-size:12px">{s["active"]} active days / yr</text>""")

    css = f"""
    .ring {{ animation: draw 1.4s ease-out 0.3s backwards; }}
    @keyframes draw {{ from {{ stroke-dashoffset: {circ:.2f}; }} }}"""
    return card(f'{s["name"][:24]}\'s GitHub Stats', "\n".join(body), css)


def languages_svg(langs: list[tuple[str, float]]) -> str:
    if not langs:
        body = '  <text x="25" y="110" class="label">No public code yet. Push a repo!</text>'
        return card("Most Used Languages", body)

    bar_x, bar_y, bar_w, bar_h = 25, 56, W - 50, 10
    parts, x = [], float(bar_x)
    for i, (_, pct) in enumerate(langs):
        w = bar_w * pct / 100
        parts.append(f'<rect x="{x:.2f}" y="{bar_y}" width="{w:.2f}" height="{bar_h}" fill="{THEME["bars"][i]}"/>')
        x += w
    body = [
        f'  <clipPath id="bar"><rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="5"/></clipPath>',
        f'  <rect x="{bar_x}" y="{bar_y}" width="{bar_w}" height="{bar_h}" rx="5" fill="{THEME["track"]}"/>',
        f'  <g clip-path="url(#bar)">{"".join(parts)}</g>',
    ]
    for i, (name, pct) in enumerate(langs):
        col, row = i % 2, i // 2
        lx, ly = 25 + col * 190, 102 + row * 34
        body.append(
            f'  <g class="fade" style="animation-delay:{200 + i * 110}ms">'
            f'<circle cx="{lx + 6}" cy="{ly - 4.5}" r="6" fill="{THEME["bars"][i]}"/>'
            f'<text x="{lx + 20}" y="{ly}" class="value" style="font-weight:600">{escape(name[:16])}</text>'
            f'<text x="{lx + 178}" y="{ly}" class="label" text-anchor="end">{pct:.1f}%</text></g>'
        )
    return card("Most Used Languages", "\n".join(body))


def placeholder_svg(title: str) -> str:
    body = (
        f'  <text x="25" y="100" class="label">Cards appear after the first workflow run.</text>\n'
        f'  <text x="25" y="124" class="label">Actions tab → "Update profile cards" → Run workflow</text>'
    )
    return card(title, body)


# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if "--placeholder" in sys.argv:
        (OUT_DIR / "stats.svg").write_text(placeholder_svg("GitHub Stats"), encoding="utf-8")
        (OUT_DIR / "languages.svg").write_text(placeholder_svg("Most Used Languages"), encoding="utf-8")
        print("Wrote placeholder cards")
        return 0

    if not USERNAME or not TOKEN:
        print("Set GH_USERNAME and GITHUB_TOKEN", file=sys.stderr)
        return 1

    summary = summarize(fetch(USERNAME), USERNAME)
    (OUT_DIR / "stats.svg").write_text(stats_svg(summary), encoding="utf-8")
    (OUT_DIR / "languages.svg").write_text(languages_svg(summary["langs"]), encoding="utf-8")
    print(json.dumps({k_: v for k_, v in summary.items() if k_ != "langs"}, indent=2))
    print("Languages:", ", ".join(f"{n} {p:.1f}%" for n, p in summary["langs"]) or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
