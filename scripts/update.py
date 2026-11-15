#!/usr/bin/env python3
"""Fill the marked blocks in README.md and docs/index.html with live numbers.

No dependencies. Runs in GitHub Actions every night.

    GH_TOKEN=... python3 scripts/update.py
    FIXTURE=data.json python3 scripts/update.py   # render without network
"""
import datetime as dt
import html
import json
import os
import re
import urllib.parse
import urllib.request

LOGIN = os.environ.get("GH_LOGIN", "ddawnlll")
TOKEN = os.environ.get("GH_TOKEN", "")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com"


def get(url, body=None):
    req = urllib.request.Request(url, data=body)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", LOGIN + "-profile")
    if TOKEN:
        req.add_header("Authorization", "Bearer " + TOKEN)
    if body:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def search(q, per_page=1):
    url = API + "/search/issues?" + urllib.parse.urlencode(
        {"q": q, "per_page": per_page, "sort": "created"})
    return get(url)


GRAPHQL = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    repositories(privacy: PUBLIC, ownerAffiliations: OWNER) { totalCount }
    recent: repositories(first: 10, privacy: PUBLIC, isFork: false,
        ownerAffiliations: OWNER, orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes { name url description pushedAt primaryLanguage { name } }
    }
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalPullRequestReviewContributions
      restrictedContributionsCount
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def fetch():
    now = dt.datetime.now(dt.timezone.utc)
    start = (now - dt.timedelta(days=365)).replace(microsecond=0)
    body = json.dumps({"query": GRAPHQL, "variables": {
        "login": LOGIN,
        "from": start.isoformat().replace("+00:00", "Z"),
        "to": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }}).encode()
    res = get(API + "/graphql", body)
    if "errors" in res:
        raise SystemExit("graphql: %s" % res["errors"])
    user = res["data"]["user"]
    cc = user["contributionsCollection"]

    days = [d for w in cc["contributionCalendar"]["weeks"]
            for d in w["contributionDays"]]
    up_q = "author:%s is:pr -user:%s" % (LOGIN, LOGIN)
    upstream = search(up_q, 10)
    # count merged separately: the item list above is capped at 10
    upstream_merged = search(up_q + " is:merged")["total_count"]

    return {
        "today": now.strftime("%Y-%m-%d"),
        "year": {
            "commits": cc["totalCommitContributions"],
            "prs": cc["totalPullRequestContributions"],
            "issues": cc["totalIssueContributions"],
            "reviews": cc["totalPullRequestReviewContributions"],
            "private": cc["restrictedContributionsCount"],
            "total": cc["contributionCalendar"]["totalContributions"],
        },
        "all": {
            "prs": search("author:%s is:pr" % LOGIN)["total_count"],
            "merged": search("author:%s is:pr is:merged" % LOGIN)["total_count"],
            "resolved": search("author:%s is:issue is:closed reason:completed"
                               % LOGIN)["total_count"],
            "repos": user["repositories"]["totalCount"],
        },
        "days": [[d["date"], d["contributionCount"]] for d in days],
        "recent": [{
            "name": r["name"],
            "url": r["url"],
            "desc": r["description"] or "",
            "lang": (r["primaryLanguage"] or {}).get("name", ""),
            "pushed": r["pushedAt"][:10],
        } for r in user["recent"]["nodes"] if r["name"] != LOGIN][:6],
        "upstream": {
            "total": upstream["total_count"],
            "merged": upstream_merged,
            "items": [{
                "repo": i["repository_url"].split("/repos/")[1],
                "title": i["title"],
                "url": i["html_url"],
                "state": "merged" if (i.get("pull_request") or {}).get("merged_at")
                         else i["state"],
            } for i in upstream["items"]],
        },
    }


# ---- rendering -----------------------------------------------------------

def n(x):
    return "{:,}".format(x)


def months(days):
    out = {}
    for date, count in days:
        out[date[:7]] = out.get(date[:7], 0) + count
    return sorted(out.items())[-12:]


LABELS = {
    "en": {
        "year": "last 365 days", "commits": "commits", "prs": "pull requests",
        "issues": "issues opened", "reviews": "code reviews",
        "private": "private contributions", "all": "all time",
        "prm": "prs opened / merged", "resolved": "issues resolved",
        "up": "prs to other projects", "repos": "public repos",
        "months": "contributions per month", "merged": "merged",
        "updated": "updated %s utc",
        "open": "open", "closed": "closed", "mergedst": "merged",
    },
    "tr": {
        "year": "son 365 gün", "commits": "commit", "prs": "pull request",
        "issues": "açılan issue", "reviews": "code review",
        "private": "private katkı", "all": "tüm zamanlar",
        "prm": "açılan / merge pr", "resolved": "çözülen issue",
        "up": "başka projelere pr", "repos": "public repo",
        "months": "aylık katkı", "merged": "merge",
        "updated": "güncellendi %s utc",
        "open": "açık", "closed": "kapalı", "mergedst": "merge edildi",
    },
}


def ledger(d, lang="en"):
    t = LABELS[lang]
    y, a = d["year"], d["all"]
    merged_up = d["upstream"].get("merged")
    if merged_up is None:  # older fixtures have no separate merged count
        merged_up = sum(1 for i in d["upstream"]["items"] if i["state"] == "merged")
    rows = [
        (t["year"], None),
        (t["commits"], n(y["commits"])),
        (t["prs"], n(y["prs"])),
        (t["issues"], n(y["issues"])),
        (t["reviews"], n(y["reviews"])),
        (t["private"], n(y["private"])),
        ("", None),
        (t["all"], None),
        (t["prm"], "%s / %s" % (n(a["prs"]), n(a["merged"]))),
        (t["resolved"], n(a["resolved"])),
        (t["up"], "%s (%d %s)" % (n(d["upstream"]["total"]), merged_up, t["merged"])),
        (t["repos"], n(a["repos"])),
        ("", None),
        (t["months"], None),
    ]
    lines = []
    for label, value in rows:
        if value is None:
            lines.append(label)
        else:
            lines.append("  " + label + " " + "." * max(2, 26 - len(label)) + " " + value)
    ms = months(d["days"])
    top = max([c for _, c in ms] + [1])
    for month, count in ms:
        bar = "#" * round(24 * count / top) if count else ""
        lines.append("  %s  %-24s %s" % (month, bar, n(count)))
    lines.append("")
    lines.append(t["updated"] % d["today"])
    return "\n".join(lines)


def md(d):
    now = "\n".join(
        "- `%s` [%s](%s)%s%s" % (
            r["pushed"], r["name"], r["url"],
            " — " + r["desc"] if r["desc"] else "",
            " (%s)" % r["lang"].lower() if r["lang"] else "")
        for r in d["recent"])
    up = "\n".join(
        "- [%s](%s) — %s, %s" % (i["repo"], i["url"], i["title"], i["state"])
        for i in d["upstream"]["items"]) or "- nothing yet"
    return {
        "now": now,
        "numbers": "```\n" + ledger(d) + "\n```",
        "upstream": up,
    }


def h(d, lang="en"):
    e = html.escape
    t = LABELS[lang]
    now = "\n".join(
        '<li><a href="%s">%s</a>%s <small>%s%s</small></li>' % (
            e(r["url"]), e(r["name"]),
            " — " + e(r["desc"]) if r["desc"] else "",
            e(r["lang"].lower()) + ", " if r["lang"] else "", r["pushed"])
        for r in d["recent"])
    state_key = {"open": "open", "closed": "closed", "merged": "mergedst"}
    up = "\n".join(
        '<li><a href="%s">%s</a> — %s, %s</li>' % (
            e(i["url"]), e(i["repo"]), e(i["title"]),
            e(t[state_key[i["state"]]] if i["state"] in state_key else i["state"]))
        for i in d["upstream"]["items"])
    if not up:
        up = "<li>%s</li>" % ("nothing yet" if lang == "en" else "henüz yok")
    return {
        "now": "<ul>\n" + now + "\n</ul>",
        "numbers": "<pre>" + e(ledger(d, lang)) + "</pre>",
        "upstream": "<ul>\n" + up + "\n</ul>",
    }


def fill(path, blocks):
    with open(path, encoding="utf-8") as f:
        text = f.read()
    for name, content in blocks.items():
        pat = re.compile(r"(<!-- %s:start -->).*?(<!-- %s:end -->)" % (name, name), re.S)
        text = pat.sub(lambda m: m.group(1) + "\n" + content + "\n" + m.group(2), text)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    if os.environ.get("FIXTURE"):
        with open(os.environ["FIXTURE"], encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = fetch()
    fill(os.path.join(ROOT, "README.md"), md(data))
    fill(os.path.join(ROOT, "docs", "index.html"), h(data, "en"))
    fill(os.path.join(ROOT, "docs", "tr", "index.html"), h(data, "tr"))


if __name__ == "__main__":
    main()
