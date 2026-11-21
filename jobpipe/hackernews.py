"""Hacker News "Ask HN: Who is hiring?" thread, through the Algolia API."""

from __future__ import annotations

import html
import re

from .regions import RegionRules

SEARCH = "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=10"
REMOTE = re.compile(r"\bremote\b", re.I)
US_ONLY = re.compile(
    r"us[- ]only|u\.s\.[- ]only|remote \(us\)|remote[- ]us\b|us[- ]based only|must (?:be|reside) in the "
    r"(?:us|united states)|us/canada only|north america only|usa only|us time ?zones? only|"
    r"americas only|remote \((?:us|usa|canada|americas)\)", re.I)
ROLE = re.compile(r"engineer|developer|analyst|qa|tester|test|designer|writer|support|scientist|manager|"
                  r"specialist|intern|associate|operations|researcher|consultant|evaluat|annotat", re.I)


def comment_text(raw_html: str) -> str:
    text = re.sub(r"<p>", "\n", raw_html or "")
    return html.unescape(re.sub(r"<[^>]+>", " ", text)).replace("\xa0", " ").strip()


def parse_post(comment_id: int, text: str, rules: RegionRules) -> dict | None:
    """One top-level comment -> a row, or None when it isn't a remote job open to your region."""
    if not REMOTE.search(text):
        return None
    if rules.region_ok(text) is not True:          # US-only, or no region you accept
        return None
    if US_ONLY.search(text) and not re.search(r"\b(?:or|and)\s+(?:europe|eu|emea|worldwide)\b", text, re.I):
        return None
    first = text.strip().split("\n")[0]
    parts = [p.strip() for p in first.split("|") if p.strip()]
    if len(parts) < 2:
        return None
    company = re.sub(r"\(?https?://\S+\)?", "", parts[0]).strip()[:60]
    role = next((p for p in parts[1:] if ROLE.search(p) and not REMOTE.search(p)), parts[1])
    where = next((p for p in parts[1:] if REMOTE.search(p)), "Remote")
    region = re.sub(r"(?i)^\s*remote\s*[-\u2013:]?\s*", "", where).strip(" ()") or ""
    return {"source": "hackernews", "title": role[:120], "company": company,
            "location": rules.label(region[:100], True), "job_url": f"https://news.ycombinator.com/item?id={comment_id}",
            "date_posted": "", "description": text[:6000], "remote": True, "region_ok": True}


def latest_thread(fetcher) -> tuple[int, str] | None:
    data = fetcher.get(SEARCH, key="hn_search")
    for hit in data.get("hits", []):
        if hit.get("title", "").startswith("Ask HN: Who is hiring"):
            return int(hit["objectID"]), hit["title"]
    return None


def fetch_hackernews(fetcher, settings, rules: RegionRules) -> list[dict]:
    thread = latest_thread(fetcher)
    if not thread:
        print("  [hackernews] no 'Who is hiring' thread found")
        return []
    story_id, title = thread
    data = fetcher.get(f"https://hn.algolia.com/api/v1/items/{story_id}", key=f"hn_{story_id}")
    rows = []
    for c in data.get("children", []):
        if c.get("text"):
            row = parse_post(c["id"], comment_text(c["text"]), rules)
            if row:
                row["date_posted"] = (c.get("created_at") or "")[:10]
                rows.append(row)
    print(f"  [hackernews] {title}: {len(data.get('children', []))} posts, {len(rows)} remote and open to you")
    return rows
