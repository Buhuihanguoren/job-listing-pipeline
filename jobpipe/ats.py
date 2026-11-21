"""Company career pages, through the public APIs of Greenhouse, Lever, Ashby, Workable,
SmartRecruiters and Recruitee. Find a company's slug with: python -m jobpipe find-ats "Name"."""

from __future__ import annotations

import html
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from bs4 import BeautifulSoup

from .regions import RegionRules

LEGAL_WORDS = (r"inc|ltd|llc|gmbh|ag|sa|s\.a|plc|bv|oy|ab|ood|ead|eood|jsc|corp|corporation|limited|co|"
               r"technologies|technology|group|holdings?|the|and|of")
REMOTE_RX = re.compile(r"remote|anywhere|worldwide|distributed|home[- ]based|work from home|wfh", re.I)


def _text(raw: str) -> str:
    return " ".join(BeautifulSoup(html.unescape(raw or ""), "html.parser").get_text(" ").split())


def normalize(s: str) -> str:
    """Lower-case ASCII words, without gender tags like (m/f/d)."""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\((?:[mfwdx]\s*/\s*)+[mfwdx]\)|\(all genders\)|\(gn\*?\)", " ", s)
    return " ".join(re.findall(r"[a-z0-9+#]+", s))


def company_words(company: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", normalize(company)) if not re.fullmatch(LEGAL_WORDS, w)]


def slug_variants(company: str) -> list[str]:
    """Likely ATS slugs for a company name: 'Acme Data Ltd' -> acmedata, acme-data, acme."""
    w = company_words(company)
    candidates = ["".join(w), "-".join(w), w[0] if w else "", "".join(w[:2])]
    out: list[str] = []
    for s in candidates:
        if len(s) >= 2 and s not in out:
            out.append(s)
    return out[:4]


# providers: answer -> list of {title, url, apply_url, location, description}
def _greenhouse(data):
    return [{"title": j.get("title", ""), "url": j.get("absolute_url", ""), "apply_url": j.get("absolute_url", ""),
             "location": (j.get("location") or {}).get("name", ""), "description": _text(j.get("content", ""))}
            for j in data.get("jobs", [])]


def _lever(data):
    out = []
    for j in data if isinstance(data, list) else []:
        parts = [j.get("descriptionPlain", "")]
        parts += [f"{block.get('text', '')}: {_text(block.get('content', ''))}" for block in j.get("lists", [])]
        parts.append(j.get("additionalPlain", ""))
        out.append({"title": j.get("text", ""), "url": j.get("hostedUrl", ""), "apply_url": j.get("applyUrl", ""),
                    "location": (j.get("categories") or {}).get("location", ""), "description": " ".join(parts)})
    return out


def _ashby(data):
    return [{"title": j.get("title", ""), "url": j.get("jobUrl", ""), "apply_url": j.get("applyUrl", ""),
             "location": j.get("location", ""), "description": j.get("descriptionPlain", "")}
            for j in data.get("jobs", [])]


def _workable(data):
    return [{"title": j.get("title", ""), "url": j.get("url") or j.get("shortlink", ""),
             "apply_url": j.get("application_url") or j.get("url", ""),
             "location": ", ".join(x for x in (j.get("city"), j.get("country")) if x),
             "description": _text(j.get("description", ""))}
            for j in data.get("jobs", [])]


def _smartrecruiters(data):
    return [{"title": j.get("name", ""),
             "url": f"https://jobs.smartrecruiters.com/{(j.get('company') or {}).get('identifier', '')}/{j.get('id', '')}",
             "apply_url": "", "description": "",
             "location": ", ".join(str(v) for v in (j.get("location") or {}).values() if v and isinstance(v, str))[:80]}
            for j in data.get("content", [])]


def _recruitee(data):
    return [{"title": j.get("title", ""), "url": j.get("careers_url", ""), "apply_url": j.get("careers_apply_url", ""),
             "location": j.get("location", ""),
             "description": _text(j.get("description", "") + " " + j.get("requirements", ""))}
            for j in data.get("offers", [])]


PROVIDERS = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true", _greenhouse),
    "lever": ("https://api.lever.co/v0/postings/{slug}?mode=json", _lever),
    "lever_eu": ("https://api.eu.lever.co/v0/postings/{slug}?mode=json", _lever),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{slug}", _ashby),
    "workable": ("https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true", _workable),
    "smartrecruiters": ("https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100", _smartrecruiters),
    "recruitee": ("https://{slug}.recruitee.com/api/offers/", _recruitee),
}


def board_or_error(fetcher, provider: str, slug: str) -> tuple[list[dict], str]:
    """(all open jobs of one company on one provider, error text or '')."""
    url, parse = PROVIDERS[provider]
    try:
        return parse(fetcher.get(url.format(slug=slug), key=f"ats_{provider}_{slug}")), ""
    except Exception as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return [], ("no job board with that slug" if status == 404 else f"{type(exc).__name__}: {exc}"[:150])


def board(fetcher, provider: str, slug: str) -> list[dict]:
    """All open jobs of one company on one provider. [] if the slug doesn't exist there."""
    return board_or_error(fetcher, provider, slug)[0]


def keep_job(job: dict, rules: RegionRules) -> tuple[str, bool, bool | None]:
    """(location label, remote?, region_ok) for one job from a company board."""
    loc = str(job.get("location") or "").strip()
    if REMOTE_RX.search(f"{loc} {job.get('title', '')}"):
        region = re.sub(r"(?i)^\s*(?:fully\s+)?remote\s*[-\u2013:,(]?\s*", "", loc).strip(" )")
        eligible = rules.region_ok(region) if region else None
        if rules.onsite_ok(region):
            eligible = True
        return rules.label(region, eligible), True, eligible
    return loc, False, rules.onsite_ok(loc)


def fetch_watchlist(fetcher, settings, rules: RegionRules) -> list[dict]:
    with ThreadPoolExecutor(8) as pool:
        boards = list(pool.map(lambda w: (w, *board_or_error(fetcher, w["provider"], w["slug"])), settings.watchlist))
    rows = []
    for w, jobs, error in boards:
        if error:
            print(f"  [watchlist] {w['company'][:28]:28} failed: {error}")
            continue
        kept = 0
        for job in jobs:
            if not job.get("url"):
                continue
            location, remote, eligible = keep_job(job, rules)
            kept += eligible is not False
            rows.append({"source": "watchlist", "title": job.get("title", "").strip(), "company": w["company"],
                         "location": location, "job_url": job["url"], "date_posted": date.today().isoformat(),
                         "description": job.get("description", ""), "remote": remote, "region_ok": eligible})
        print(f"  [watchlist] {w['company'][:28]:28} {len(jobs):4d} jobs, {kept:3d} you can take")
    return rows


def find_ats(fetcher, company: str) -> list[tuple[str, str, int, str]]:
    """Providers that have a job board for this company: (provider, slug, jobs, example title)."""
    pairs = [(p, s) for s in slug_variants(company) for p in PROVIDERS]
    with ThreadPoolExecutor(8) as pool:
        found = list(pool.map(lambda ps: (ps, board(fetcher, *ps)), pairs))
    return [(p, s, len(jobs), jobs[0]["title"]) for (p, s), jobs in found if jobs]
