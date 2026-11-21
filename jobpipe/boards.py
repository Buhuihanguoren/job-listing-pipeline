"""Remote job boards: Remotive, Remote OK, Jobicy, Himalayas, We Work Remotely, Working Nomads.

Each board has a parser (tested offline against tests/data) and a fetcher."""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .regions import RegionRules

COLUMNS = ["source", "title", "company", "location", "job_url", "date_posted", "description"]
pause = time.sleep          # replaced in tests


# helpers
def fix_mojibake(s: str) -> str:
    """Fix UTF-8 text that was decoded as Latin-1 (Remote OK does this)."""
    if not s or not re.search(r"[\u00c3\u00c2][\x80-\xbf]", s):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def html_to_text(html: str) -> str:
    if not html:
        return ""
    return re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ")).strip()


def iso_date(value) -> str:
    """Epoch seconds, ISO 8601 or RFC 822 -> 'YYYY-MM-DD'. '' if it can't be read."""
    if value in (None, ""):
        return ""
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(int(value), tz=timezone.utc).date().isoformat()
        s = str(value).strip()
        if re.match(r"\d{4}-\d{2}-\d{2}", s):
            return s[:10]
        return parsedate_to_datetime(s).date().isoformat()
    except Exception:
        return ""


def make_row(source, title, company, region, url, date, description, eligible, rules: RegionRules) -> dict:
    title, company, region, description = (fix_mojibake(v or "") for v in (title, company, region, description))
    return {
        "source": source,
        "title": title.strip(),
        "company": company.strip(),
        "location": rules.label(region, eligible),
        "job_url": (url or "").strip(),
        "date_posted": iso_date(date),
        "description": html_to_text(description),
        "remote": True,
        "region_ok": eligible,
    }


# parsers
def parse_remotive(payload: dict, rules: RegionRules) -> list[dict]:
    rows = []
    for j in payload.get("jobs", []):
        region = j.get("candidate_required_location", "")
        rows.append(make_row("remotive", j.get("title"), j.get("company_name"), region, j.get("url"),
                             j.get("publication_date"), j.get("description"), rules.region_ok(region), rules))
    return rows


def parse_himalayas(payload: dict, rules: RegionRules) -> list[dict]:
    rows = []
    for j in payload.get("jobs", []):
        countries = j.get("locationRestrictions") or []
        if countries:
            region = ", ".join(countries)
            eligible = rules.region_ok(region)
        else:
            region = "Worldwide"
            eligible = rules.timezones_ok(j.get("timezoneRestrictions")) is not False
        rows.append(make_row("himalayas", j.get("title"), j.get("companyName"), region,
                             j.get("applicationLink") or j.get("guid"), j.get("pubDate"),
                             j.get("description") or j.get("excerpt"), eligible, rules))
    return rows


def parse_jobicy(payload: dict, rules: RegionRules) -> list[dict]:
    rows = []
    for j in payload.get("jobs", []):
        region = re.sub(r"\s*,\s*", ", ", j.get("jobGeo", "")).strip()
        rows.append(make_row("jobicy", j.get("jobTitle"), j.get("companyName"), region, j.get("url"),
                             j.get("pubDate"), j.get("jobDescription") or j.get("jobExcerpt"),
                             rules.region_ok(region), rules))
    return rows


def parse_workingnomads(payload: list, rules: RegionRules) -> list[dict]:
    rows = []
    for j in payload or []:
        region = j.get("location", "")
        rows.append(make_row("workingnomads", j.get("title"), j.get("company_name"), region, j.get("url"),
                             j.get("pub_date"), j.get("description"), rules.region_ok(region), rules))
    return rows


def parse_weworkremotely(xml_text: str, rules: RegionRules) -> list[dict]:
    rows = []
    for item in ET.fromstring(xml_text).iter("item"):
        def text(tag):
            el = item.find(tag)
            return (el.text or "").strip() if el is not None and el.text else ""
        company, _, title = text("title").partition(": ")
        if not title:                                   # no "Company: " prefix
            company, title = "", text("title")
        region = ", ".join(p for p in (text("region"), text("country")) if p)
        rows.append(make_row("weworkremotely", title, company, region, text("link") or text("guid"),
                             text("pubDate"), text("description"), rules.region_ok(region), rules))
    return rows


def parse_remoteok(payload: list, rules: RegionRules) -> list[dict]:
    rows = []
    for j in payload or []:
        if "position" not in j:                         # the first element is the API's legal notice
            continue
        region = j.get("location", "")
        rows.append(make_row("remoteok", j.get("position"), j.get("company"), region, j.get("url"),
                             j.get("date") or j.get("epoch"), j.get("description"), rules.region_ok(region), rules))
    return rows


# fetchers
def fetch_remotive(fetcher, settings, rules):
    return parse_remotive(fetcher.get("https://remotive.com/api/remote-jobs", key="remotive"), rules)


def fetch_himalayas(fetcher, settings, rules):
    """Keyword search, 20 results a page. A 429 (rate limit) stops further paging for this run."""
    rows, max_pages = [], settings.himalayas_max_pages
    country = f"&country={quote(settings.country)}" if settings.country else ""
    for q in settings.himalayas_queries:
        key = "himalayas_" + re.sub(r"\W+", "_", q)
        for page in range(1, max_pages + 1):
            url = f"https://himalayas.app/jobs/api/search?q={quote(q)}{country}&page={page}"
            try:
                data = fetcher.get(url, key=key if page == 1 else f"{key}_p{page}")
            except requests.HTTPError as exc:
                code = exc.response.status_code if exc.response is not None else "?"
                print(f"  [himalayas] HTTP {code} on '{q}' page {page}, no more extra pages this run")
                max_pages = 1
                pause(3)
                break
            got = parse_himalayas(data, rules)
            rows += got
            total = int(data.get("totalCount") or 0) if isinstance(data, dict) else 0
            pause(1.2)
            if not got or page * 20 >= total:
                break
    return rows


def fetch_jobicy(fetcher, settings, rules):
    rows = []
    for geo in settings.jobicy_geos:
        url = f"https://jobicy.com/api/v2/remote-jobs?count=100&geo={quote(geo)}"
        rows += parse_jobicy(fetcher.get(url, key=f"jobicy_{geo}"), rules)
    return rows


def fetch_workingnomads(fetcher, settings, rules):
    return parse_workingnomads(fetcher.get("https://www.workingnomads.com/api/exposed_jobs/", key="workingnomads"),
                               rules)


def fetch_weworkremotely(fetcher, settings, rules):
    return parse_weworkremotely(fetcher.get("https://weworkremotely.com/remote-jobs.rss", as_json=False,
                                            key="weworkremotely"), rules)


def fetch_remoteok(fetcher, settings, rules):
    return parse_remoteok(fetcher.get("https://remoteok.com/api", key="remoteok"), rules)


FETCHERS = {
    "remotive": fetch_remotive,
    "remoteok": fetch_remoteok,
    "jobicy": fetch_jobicy,
    "himalayas": fetch_himalayas,
    "weworkremotely": fetch_weworkremotely,
    "workingnomads": fetch_workingnomads,
}
