"""Dedup, filter and score the listings.

Word lists match whole words. A * at the end matches any ending (test* = tester, testing)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd
from rapidfuzz import fuzz

from .boards import COLUMNS
from .settings import Lists, Settings, clean_url, norm_url

MAX_DESCRIPTION = 6000

DROP_REASONS = ["hidden by you", "outside your region", "blocked company", "blocked title word", "blocked word",
                "title doesn't match", "too old"]


# word matching
def word_pattern(word: str) -> re.Pattern:
    """'qa' -> whole word qa; 'test*' -> test, tester, testing; phrases allow any spacing."""
    w = word.strip().lower()
    star = w.endswith("*")
    body = re.escape(w.rstrip("*")).replace(r"\ ", r"\s+")
    return re.compile(r"(?<!\w)" + body + (r"\w*" if star else r"(?!\w)"), re.I)


class WordSet:
    def __init__(self, words):
        self.words = [w for w in words if w.strip()]
        self._patterns = [(w, word_pattern(w)) for w in self.words]

    def first(self, text: str) -> str | None:
        return next((w for w, p in self._patterns if p.search(text or "")), None)

    def all(self, text: str) -> list[str]:
        return [w for w, p in self._patterns if p.search(text or "")]


# duplicates
_PARENS = re.compile(r"\([^)]*\)")
_GENDER = re.compile(r"\b(?:m\s*[/\\]\s*[fwd]\s*[/\\]\s*[fwd]|m\s*[/\\]\s*f|f\s*[/\\]\s*m)\b", re.I)
_SENIORITY = re.compile(r"\b(senior|sr\.?|junior|jr\.?|mid|mid-level|lead|principal|staff|entry[- ]level)\b", re.I)
_LEVELS = {
    "junior": re.compile(r"\b(junior|jr\.?|intern|internship|trainee|graduate|entry[- ]level)\b", re.I),
    "senior": re.compile(r"\b(senior|sr\.?|lead|principal|staff)\b", re.I),
}


def normalize_title(t: str) -> str:
    s = str(t or "").lower()
    s = _PARENS.sub(" ", s)
    s = _GENDER.sub(" ", s)
    s = _SENIORITY.sub(" ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def seniority(t: str) -> str:
    return next((level for level, rx in _LEVELS.items() if rx.search(str(t or ""))), "any")


def fuzzy_dedup(df: pd.DataFrame, threshold: int = 90) -> pd.DataFrame:
    """Merge near-duplicate titles per company. Junior and senior versions stay separate."""
    if df.empty:
        return df
    df = df.reset_index(drop=True)
    group_key = df["company"].str.lower().str.strip() + "|" + df["title"].map(seniority)
    norm = df["title"].map(normalize_title)
    length = df["description"].str.len()
    keep: list[int] = []
    for _, idx in group_key.groupby(group_key).groups.items():
        chosen: list[str] = []
        for i in sorted(idx, key=lambda i: -length[i]):
            if any(fuzz.token_sort_ratio(norm[i], c) >= threshold for c in chosen):
                continue
            chosen.append(norm[i])
            keep.append(i)
    return df.loc[sorted(keep)].reset_index(drop=True)


def drop_same_text(df: pd.DataFrame, min_length: int = 200) -> pd.DataFrame:
    """Same title and same long description under two company names (agency and client)."""
    if df.empty:
        return df
    desc = df["description"].str.lower().str.replace(r"\W+", " ", regex=True).str.strip()
    fingerprint = df["title"].map(normalize_title) + "|" + desc
    duplicate = fingerprint.duplicated() & (desc.str.len() >= min_length)
    return df[~duplicate].reset_index(drop=True)


# pay
_MONEY = r"(?:€|\$|£|\beur\b|\busd\b|\bgbp\b|\bbgn\b|\bchf\b|\bpln\b|\bron\b|лв)"
_AMOUNT = r"(?:\d{1,3}(?:[ ,.]?\d{3})+|\d{3,6}|\d{2,3}\s?k)(?![\d,.]*\s?(?:m\b|mn\b|million|billion|bn\b|b\b))"
PAY_RE = re.compile(
    rf"{_MONEY}\s?\d{{2,3}}(?:[.,]\d{{2}})?\s?(?:/|per|an?)\s?(?:h|hr|hour)\b"      # hourly: $30/hour
    rf"|{_MONEY}\s?{_AMOUNT}(?:\s?(?:-|\u2013|to)\s?{_MONEY}?\s?{_AMOUNT})?(?:\s?{_MONEY})?"
    rf"|{_AMOUNT}(?:\s?(?:-|\u2013|to)\s?{_AMOUNT})?\s?{_MONEY}", re.I)
# An amount only counts as pay next to a pay word ("salary", "compensation") or a period ("per month", "/hour").
_PAY_WORDS = re.compile(r"salar|\bpay\b|\bpaid\b|compensation|\bwage|\brate\b|remuneration|\bearn|\bincome|"
                        r"\bbase\b|\bote\b|заплата|възнаграждение", re.I)
_PERIOD = re.compile(r"/\s?(?:h|hr|hour|month|mo|year|yr)\b|per\s+(?:hour|month|year|annum)|\ban?\s+(?:hour|month|year)\b|"
                     r"\bp\.?a\b|annual|monthly|hourly|\bgross\b|\bbrutto\b|\bnet\b|бруто|нето|на месец", re.I)


def pay_hint(text: str) -> str:
    """First amount that looks like pay, or ''. Needs a pay word or a period next to it."""
    text = text or ""
    for m in PAY_RE.finditer(text):
        before, after = text[max(0, m.start() - 60):m.start()], text[m.end():m.end() + 30]
        if _PAY_WORDS.search(before) or _PERIOD.search(m.group(0) + " " + after):
            return m.group(0).strip()
    return ""


# the pipeline
@dataclass
class Result:
    jobs: pd.DataFrame
    dropped: pd.DataFrame
    raw_count: int = 0
    duplicates: int = 0
    reasons: dict[str, int] = field(default_factory=dict)

    @property
    def new_count(self) -> int:
        return int(self.jobs["new"].sum()) if len(self.jobs) else 0


def _yes_no_unknown(value) -> bool | None:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in ("true", "false"):
        return value.strip().lower() == "true"
    return None


def tidy(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.copy()
    for col in COLUMNS + ["remote", "region_ok"]:
        if col not in df.columns:
            df[col] = None if col == "region_ok" else ""
    for col in COLUMNS:
        df[col] = df[col].fillna("").astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    df["description"] = df["description"].str[:MAX_DESCRIPTION]
    df["job_url"] = df["job_url"].map(clean_url)
    df["remote"] = df["remote"].map(lambda v: _yes_no_unknown(v) is True)
    df["region_ok"] = pd.Series([_yes_no_unknown(v) for v in df["region_ok"]], index=df.index, dtype=object)
    return df[(df["title"] != "") & (df["job_url"] != "")].reset_index(drop=True)


def drop_reason(row, s: Settings, lists: Lists, titles: WordSet, title_blocks: WordSet, word_blocks: WordSet,
                today: date) -> str | None:
    if norm_url(row["job_url"]) in lists.hidden:
        return "hidden by you"
    if row["region_ok"] is False:
        return "outside your region"
    company = row["company"].lower()
    if company and any(b in company for b in lists.companies):
        return "blocked company"
    if title_blocks.first(row["title"]):
        return "blocked title word"
    if word_blocks.first(f"{row['title']} {row['description']}"):
        return "blocked word"
    if titles.words and not titles.first(row["title"]):
        return "title doesn't match"
    if s.max_age_days and row["date_posted"]:
        try:
            if (today - date.fromisoformat(row["date_posted"][:10])).days > s.max_age_days:
                return "too old"
        except ValueError:
            pass
    return None


def score(row, s: Settings, title_words: dict[str, re.Pattern], desc_words: dict[str, re.Pattern]):
    points, why = 0, []
    for word, pattern in title_words.items():
        if pattern.search(row["title"]):
            pts = s.title_points[word]
            points += pts
            why.append(f"{pts:+d} {word.rstrip('*')}")
    for word, pattern in desc_words.items():
        if pattern.search(row["description"]):
            pts = s.description_points[word]
            points += pts
            why.append(f"{pts:+d} {word.rstrip('*')}")
    if row["remote"] and s.remote_points:
        points += s.remote_points
        why.append(f"{s.remote_points:+d} remote")
    pay = pay_hint(f"{row['title']} {row['description']}")
    if pay and s.pay_points:
        points += s.pay_points
        why.append(f"{s.pay_points:+d} salary stated")
    return points, ", ".join(why), pay


def process(raw: pd.DataFrame, s: Settings, lists: Lists, seen: set[str], today: date | None = None) -> Result:
    today = today or date.today()
    df = tidy(raw)
    raw_count = len(df)
    df = drop_same_text(fuzzy_dedup(df))
    duplicates = raw_count - len(df)

    titles, title_blocks, word_blocks = WordSet(s.title_must_contain), WordSet(lists.title_words), WordSet(lists.words)
    reasons = df.apply(lambda r: drop_reason(r, s, lists, titles, title_blocks, word_blocks, today), axis=1) \
        if len(df) else pd.Series(dtype=object)
    dropped = df[reasons.notna()].assign(reason=reasons[reasons.notna()])
    jobs = df[reasons.isna()].copy()

    title_words = {w: word_pattern(w) for w in s.title_points}
    desc_words = {w: word_pattern(w) for w in s.description_points}
    if len(jobs):
        scored = jobs.apply(lambda r: score(r, s, title_words, desc_words), axis=1, result_type="expand")
        jobs["score"], jobs["why"], jobs["pay"] = scored[0], scored[1], scored[2]
        jobs["new"] = ~jobs["job_url"].map(norm_url).isin(seen)
    else:
        jobs = jobs.assign(score=pd.Series(dtype=int), why="", pay="", new=pd.Series(dtype=bool))
    jobs = jobs.sort_values(["score", "date_posted"], ascending=[False, False]).reset_index(drop=True)

    counts = dropped["reason"].value_counts().to_dict() if len(dropped) else {}
    return Result(jobs=jobs, dropped=dropped.reset_index(drop=True), raw_count=raw_count, duplicates=duplicates,
                  reasons={r: int(counts[r]) for r in DROP_REASONS if r in counts})
