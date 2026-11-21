"""Write jobs.csv, dropped.csv and report.md, and print the summary."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .pipeline import Result

JOB_COLUMNS = ["score", "new", "title", "company", "location", "pay", "why", "job_url", "date_posted", "source",
               "description"]
DROPPED_COLUMNS = ["reason", "title", "company", "location", "job_url", "date_posted", "source"]
REASON_TEXT = {
    "hidden by you": "hidden by you (lists/hidden_jobs.txt)",
    "outside your region": "outside your region",
    "blocked company": "blocked company (lists/block_companies.txt)",
    "blocked title word": "blocked word in the title (lists/block_title_words.txt)",
    "blocked word": "blocked word in the ad (lists/block_words.txt)",
    "title doesn't match": "title doesn't match [filters] title_must_contain",
    "too old": "older than [filters] max_age_days",
}


def _cell(value) -> str:
    return str(value).replace("|", "/").replace("\n", " ").strip()


def summary_lines(result: Result, counts: dict[str, int], errors: dict[str, str]) -> list[str]:
    lines = [f"{len(result.jobs)} jobs kept out of {result.raw_count:,} listings, {result.new_count} new since last run."]
    removed = [f"{result.duplicates} duplicates"] if result.duplicates else []
    removed += [f"{n} {reason}" for reason, n in result.reasons.items()]
    if removed:
        lines.append("Removed: " + ", ".join(removed) + ".")
    failed = [f"{s} ({e[:80]})" for s, e in errors.items()]
    if failed:
        lines.append("Failed sources: " + ", ".join(failed))
    return lines


def write_outputs(result: Result, out_dir: Path, day: str, counts: dict[str, int], errors: dict[str, str],
                  warnings: list[str], top: int) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"jobs": out_dir / "jobs.csv", "dropped": out_dir / "dropped.csv", "report": out_dir / "report.md"}
    jobs = result.jobs.reindex(columns=JOB_COLUMNS)
    jobs["new"] = jobs["new"].map({True: "new", False: ""})
    jobs.to_csv(paths["jobs"], index=False, encoding="utf-8-sig")
    result.dropped.reindex(columns=DROPPED_COLUMNS).to_csv(paths["dropped"], index=False, encoding="utf-8-sig")

    md = [f"# Job report, {day}", ""]
    md += summary_lines(result, counts, errors)[:1] + [""]
    md += [f"## Top {min(top, len(result.jobs))}", "",
           "| # | Score | New | Job | Company | Where | Salary | Why |",
           "|--:|--:|:-:|---|---|---|---|---|"]
    for i, row in enumerate(result.jobs.head(top).itertuples(), 1):
        md.append(f"| {i} | {row.score} | {'new' if row.new else ''} | [{_cell(row.title)}]({row.job_url}) | "
                  f"{_cell(row.company)} | {_cell(row.location)} | {_cell(row.pay)} | {_cell(row.why)} |")
    md += ["", "## Sources", "", "| Source | Listings | Note |", "|---|--:|---|"]
    for source in sorted(counts):
        note = f"failed: {_cell(errors[source])[:100]}" if source in errors else ""
        md.append(f"| {source} | {counts[source]} | {note} |")
    md += ["", "## Removed", ""]
    if result.duplicates:
        md.append(f"- {result.duplicates} duplicates (the same job on several boards, or the same ad under two names)")
    for reason, n in result.reasons.items():
        md.append(f"- {n} {REASON_TEXT.get(reason, reason)}")
    md += ["", "Every removed job is listed in dropped.csv with its reason, so you can check the filters."]
    if warnings:
        md += ["", "## Warnings", ""] + [f"- {w}" for w in warnings]
    paths["report"].write_text("\n".join(md) + "\n", encoding="utf-8")
    return paths


def print_summary(result: Result, counts: dict[str, int], errors: dict[str, str], warnings: list[str],
                  paths: dict[str, Path], top: int) -> None:
    print()
    print("Sources: " + ", ".join(f"{s} {n}" for s, n in sorted(counts.items())))
    for line in summary_lines(result, counts, errors):
        print(line)
    for w in warnings:
        print(f"Warning: {w}")
    if len(result.jobs):
        print(f"\nTop {min(top, len(result.jobs))}:")
        for i, row in enumerate(result.jobs.head(top).itertuples(), 1):
            new = "NEW " if row.new else ""
            pay = f"  {row.pay}" if row.pay else ""
            print(f"{i:3d}. {row.score:4d}  {new}{row.title[:70]} | {row.company[:30]} | {row.location[:40]}{pay}")
            print(f"            {row.job_url}")
    print(f"\nFull list: {paths['jobs']}\nReport:    {paths['report']}\nRemoved:   {paths['dropped']}")
