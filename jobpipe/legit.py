"""Is the job real? Own careers page, website, domain age and scam phrases."""

from __future__ import annotations

import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime

from rapidfuzz import fuzz

from .ats import PROVIDERS, board, company_words, normalize, slug_variants

RED_FLAGS = re.compile(
    r"(?:application|registration|training|placement|processing|onboarding) fee|"
    r"pay (?:for|a fee for) (?:the |your )?(?:training|course|equipment)|"
    # Messenger apps only count as a hiring channel ("interview via Telegram"), not as a channel the job serves.
    r"(?:contact (?:us|me|our (?:hr|recruit\w*|hiring|team))|reach (?:us|me|out to (?:us|me))|apply|"
    r"interview\w*|send (?:your |us )?(?:cv|resume|application)|recruit\w*)[^.\n]{0,30}\b(?:telegram|whatsapp|signal)\b|"
    r"\b(?:telegram|whatsapp)\b[^.\n]{0,20}(?:interview|recruit|hr\b|hiring)|"
    r"cash(?:ing)? (?:a |the )?(?:check|cheque)|bank (?:account )?details|"
    r"social security number|passport (?:copy|scan)|crypto(?:currency)? (?:wallet|payment)|"
    r"guaranteed (?:job|income|placement)|unlimited earning", re.I)
NEGATION = re.compile(r"\b(?:never|not|no|don['\u2019]?t|won['\u2019]?t|will not|do not|beware|warning|scam|fraud\w*)\b", re.I)

SKIP_DOMAINS = (
    "linkedin.", "himalayas.", "greenhouse.io", "lever.co", "ashbyhq.", "workable.", "smartrecruiters.",
    "recruitee.", "glassdoor.", "indeed.", "facebook.", "twitter.", "x.com", "instagram.", "youtube.",
    "google.", "goo.gl", "bit.ly", "github.", "jobicy.", "remotive.", "weworkremotely.", "workingnomads.",
    "remoteok.", "ycombinator.", "teamtailor.", "personio.", "bamboohr.", "gmail.", "outlook.", "yahoo.",
    "hotmail.", "w3.org", "schema.org", "wikipedia.", "medium.com", "t.me", "wa.me", "calendly.", "typeform.",
    "forms.gle", "youtu.be",
)
URL_RE = re.compile(r"https?://(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.I)
EMAIL_RE = re.compile(r"[\w.+-]+@([a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.I)
ATS_URL_SLUGS = [
    ("greenhouse", re.compile(r"greenhouse\.io/(?:embed/job_board\?for=)?([\w-]+)", re.I)),
    ("lever_eu", re.compile(r"eu\.lever\.co/([\w-]+)", re.I)),
    ("lever", re.compile(r"(?<!eu\.)lever\.co/([\w-]+)", re.I)),
    ("ashby", re.compile(r"ashbyhq\.com/([\w-]+)", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/([\w-]+)", re.I)),
    ("smartrecruiters", re.compile(r"smartrecruiters\.com/([\w-]+)", re.I)),
    ("recruitee", re.compile(r"([\w-]+)\.recruitee\.com", re.I)),
]


def red_flag_hits(text: str) -> list[str]:
    """Scam phrases, except inside anti-scam notices ("we will never interview over WhatsApp")."""
    text = text or ""
    hits = set()
    for m in RED_FLAGS.finditer(text):
        if NEGATION.search(text[max(0, m.start() - 60):m.start()]):
            continue
        hits.add(m.group(0).lower())
    return sorted(hits)


def registrable(domain: str) -> str:
    """jobs.example.co.uk -> example.co.uk"""
    parts = domain.lower().strip(".").split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "ac", "gov") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def find_own_posting(fetcher, company: str, title: str, text: str = "", watchlist=()) -> dict | None:
    """The same job on the company's own ATS, or None. Needs a close title match (88/100)."""
    pairs = []
    for provider, rx in ATS_URL_SLUGS:
        for slug in rx.findall(text or ""):
            if slug.lower() not in ("embed", "jobs", "api", "v1", "apply"):
                pairs.append((provider, slug.lower()))
    pairs += [(p, s) for s in slug_variants(company) for p in PROVIDERS]
    words = {w for w in company_words(company) if len(w) >= 4}
    pairs += [(w["provider"], w["slug"]) for w in watchlist
              if words & {x for x in company_words(w["company"]) if len(x) >= 4}]
    pairs = list(dict.fromkeys(pairs))
    with ThreadPoolExecutor(8) as pool:
        boards = list(pool.map(lambda ps: (ps, board(fetcher, *ps)), pairs))
    want = normalize(title)
    best, best_score = None, 0.0
    for (provider, slug), jobs in boards:
        for job in jobs:
            have = normalize(job["title"])
            # token_set alone rates "QA Engineer" 100 against "QA Engineer Intern"; the average prefers exact titles.
            score = (fuzz.token_set_ratio(want, have) + fuzz.token_sort_ratio(want, have)) / 2
            if score > best_score:
                best, best_score = dict(job, provider=provider, slug=slug), score
    return dict(best, match=round(best_score)) if best and best_score >= 88 else None


def site_check(fetcher, domain: str, words: list[str]) -> dict:
    got = fetcher.page(f"https://{domain}")
    if got is None or got[0] >= 400:
        return {"site_ok": False, "site_title": ""}
    page = got[1]
    m = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
    title = " ".join(html.unescape(m.group(1)).split())[:80] if m else ""
    low = page[:200000].lower()
    return {"site_ok": any(w in low for w in words if len(w) >= 3), "site_title": title}


def find_domain(fetcher, company: str, text: str, guess: bool = True) -> tuple[str | None, str]:
    """(domain, "posting" or "guess"). A guessed domain can belong to another company."""
    words = [w for w in company_words(company) if len(w) >= 3]
    found = [registrable(d) for d in URL_RE.findall(text or "") + EMAIL_RE.findall(text or "")]
    found = [d for d in found if not any(s in d for s in SKIP_DOMAINS)]
    named = [d for d in found if any(w in d.replace("-", "") for w in words)]
    if named:
        return max(set(named), key=named.count), "posting"
    if not guess:
        return None, ""
    guesses = [f"{s}.{tld}" for s in slug_variants(company)[:2] for tld in ("com", "io", "ai", "eu")]
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(lambda d: (d, site_check(fetcher, d, words)), guesses))
    for domain, result in results:
        if result["site_ok"]:
            return domain, "guess"
    return None, ""


def domain_age_years(fetcher, domain: str) -> float | None:
    """Years since the domain was registered, from the registry's RDAP server (IANA bootstrap list)."""
    dom = registrable(domain)
    bootstrap = fetcher.try_get("https://data.iana.org/rdap/dns.json", key="rdap_bootstrap", max_age_hours=720)
    if not bootstrap:
        return None
    tld = dom.rsplit(".", 1)[-1]
    base = next((urls[0].rstrip("/") + "/" for tlds, urls in bootstrap.get("services", []) if tld in tlds and urls),
                None)
    if not base:
        return None
    data = fetcher.try_get(f"{base}domain/{dom}", max_age_hours=0)
    for event in (data or {}).get("events", []):
        if event.get("eventAction") == "registration":
            try:
                registered = datetime.fromisoformat(event["eventDate"][:10]).date()
            except (KeyError, ValueError):
                return None
            return round((date.today() - registered).days / 365.25, 1)
    return None


def verdict(ev: dict) -> str:
    if ev["red_flags"]:
        return "Red flags: " + "; ".join(ev["red_flags"])
    if ev["own_posting"]:
        return "Looks real: the job is on the company's own careers page"
    if ev["domain_source"] == "posting" and ev.get("site_ok") and (ev.get("domain_age_years") or 0) >= 2:
        return "Probably real: the posting links an established company website"
    return "Not confirmed: check the company yourself before sending anything"


def check_company(fetcher, company: str, title: str = "", text: str = "", watchlist=()) -> dict:
    own = find_own_posting(fetcher, company, title, text, watchlist) if title else None
    ev = {"company": company, "title": title, "red_flags": red_flag_hits(text),
          "own_posting": f"{own['url']} ({own['provider']}, title match {own['match']})" if own else None}
    domain, source = find_domain(fetcher, company, f"{text} {(own or {}).get('description', '')}", guess=own is None)
    ev["domain"], ev["domain_source"] = domain, source
    if domain:
        ev.update(site_check(fetcher, domain, [w for w in company_words(company) if len(w) >= 3]))
        ev["domain_age_years"] = domain_age_years(fetcher, domain)
    ev["verdict"] = verdict(ev)
    return ev
