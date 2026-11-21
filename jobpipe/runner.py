"""One run: read the sources, process the listings, write the output."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

import pandas as pd

from . import ats, boards, hackernews, health, report
from .http import Fetcher
from .pipeline import Result, process
from .regions import RegionRules
from .settings import Settings, load_lists, norm_url

SOURCES = {**boards.FETCHERS, "hackernews": hackernews.fetch_hackernews, "watchlist": ats.fetch_watchlist}


def make_fetcher(s: Settings) -> Fetcher:
    return Fetcher(cache_dir=s.cache_dir, cache_hours=s.cache_hours, user_agent=s.user_agent)


def collect(s: Settings, fetcher, rules: RegionRules, only: list[str] | None = None):
    """(DataFrame of all rows, {source: listings}, {source: error})"""
    rows, counts, errors = [], {}, {}
    for name in only or s.enabled_sources():
        if name == "watchlist" and not s.watchlist:
            continue
        print(f"Reading {name} ...")
        try:
            got = SOURCES[name](fetcher, s, rules)
        except Exception as exc:                     # one broken source must not stop the run
            errors[name] = f"{type(exc).__name__}: {exc}"
            counts[name] = 0
            print(f"  [{name}] failed: {errors[name][:120]}")
            continue
        counts[name] = len(got)
        rows += got
    return pd.DataFrame(rows), counts, errors


def load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with open(path, newline="", encoding="utf-8") as fh:
        return {row["url"] for row in csv.DictReader(fh) if row.get("url")}


def remember(path: Path, result: Result, day: str) -> None:
    new_file = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        if new_file:
            writer.writerow(["url", "first_seen"])
        for url in result.jobs.loc[result.jobs["new"], "job_url"] if len(result.jobs) else []:
            writer.writerow([norm_url(url), day])


def run(s: Settings, only: list[str] | None = None, today: date | None = None, fetcher=None, quiet: bool = False):
    today = today or date.today()
    day = today.isoformat()
    rules = RegionRules.from_settings(s)
    fetcher = fetcher or make_fetcher(s)
    raw, counts, errors = collect(s, fetcher, rules, only)

    out = s.output_dir
    out.mkdir(parents=True, exist_ok=True)
    result = process(raw, s, load_lists(s), load_seen(out / "seen.csv"), today)
    health.append_history(out / "history.csv", day, counts, errors)
    warnings = health.check(out / "history.csv", day, counts)
    # a partial run (--sources) gets its own folder, so it never overwrites the day's full report
    folder = day if not only else f"{day}_{'-'.join(only) if len(only) <= 3 else f'{len(only)}-sources'}"
    paths = report.write_outputs(result, out / folder, day, counts, errors, warnings, s.top)
    remember(out / "seen.csv", result, day)
    if not quiet:
        report.print_summary(result, counts, errors, warnings, paths, s.top)
    return result, paths
