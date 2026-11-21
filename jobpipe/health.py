"""Warn when a source returns far fewer jobs than usual (history in output/history.csv)."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from statistics import median

FIELDS = ["date", "time", "source", "listings", "error"]


def append_history(path: Path, day: str, counts: dict[str, int], errors: dict[str, str]) -> None:
    new_file = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().strftime("%H:%M")
    with open(path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        for source, n in counts.items():
            writer.writerow({"date": day, "time": now, "source": source, "listings": n,
                             "error": errors.get(source, "")})


def load_history(path: Path) -> dict[str, dict[str, int]]:
    """{date: {source: listings}}, keeping the last run of each day."""
    out: dict[str, dict[str, int]] = {}
    if not path.exists():
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                out.setdefault(row["date"], {})[row["source"]] = int(row["listings"])
            except (KeyError, ValueError):
                continue
    return out


def alerts(today: dict[str, int], earlier: dict[str, dict[str, int]]) -> list[str]:
    """Warnings for sources that ran today with far fewer listings than usual."""
    usual: dict[str, list[int]] = {}
    for day in sorted(earlier)[-7:]:
        for source, n in earlier[day].items():
            usual.setdefault(source, []).append(n)
    out = []
    for source, now in today.items():
        values = usual.get(source, [])
        if len(values) < 2:
            continue
        typical = median(values)
        if typical >= 5 and now < max(1, 0.3 * typical):
            out.append(f"{source}: {now} listings this run, usually about {int(typical)}. "
                       f"The site may have changed or be blocking requests.")
    return out


def check(path: Path, day: str, today: dict[str, int] | None = None) -> list[str]:
    history = load_history(path)
    if today is None:
        today = history.get(day, {})
    return alerts(today, {d: c for d, c in history.items() if d < day})
