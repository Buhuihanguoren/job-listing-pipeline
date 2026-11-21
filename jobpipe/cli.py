"""Command line: python -m jobpipe <command>"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, ats, health, legit, runner
from .boards import html_to_text
from .settings import ALL_SOURCES, LIST_FILES, ConfigError, add_to_list, init, load_settings

HELP = """\
commands:
  init                      create config.toml and lists/ in this folder (first time only)
  run                       read all sources, write output/<date>/report.md and jobs.csv
  hide LINK [LINK ...]      never show these jobs again (applied, or not interested)
  block company NAME ...    never show jobs from these companies
  block word WORD ...       hide jobs whose ad contains these words
  block title WORD ...      hide jobs whose title contains these words (e.g. senior)
  check-company NAME        is this company and job real? (website, own careers page, red flags)
  find-ats NAME             find a company's careers system, to add it to the [[watchlist]]
  health                    warn about sources that returned far fewer jobs than usual

examples:
  python -m jobpipe run
  python -m jobpipe run --sources remotive,hackernews
  python -m jobpipe hide https://remotive.com/remote-jobs/qa/some-job-123
  python -m jobpipe block company "Acme Recruiting"
  python -m jobpipe check-company "Acme" --title "QA Engineer" --url https://example.com/jobs/1
"""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m jobpipe", description="Collect, clean and rank job listings.",
                                epilog=HELP, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", default="config.toml", help="settings file (default: config.toml in this folder)")
    p.add_argument("--version", action="version", version=f"job-listing-pipeline {__version__}")
    sub = p.add_subparsers(dest="command", metavar="command")

    sub.add_parser("init", help="create config.toml and lists/")
    r = sub.add_parser("run", help="read all sources and write the report")
    r.add_argument("--sources", help=f"comma-separated subset of: {', '.join(ALL_SOURCES)}")
    r.add_argument("--top", type=int, help="how many jobs to show (default: [output] top)")

    h = sub.add_parser("hide", help="never show these jobs again")
    h.add_argument("links", nargs="+")

    b = sub.add_parser("block", help="block companies or words")
    b.add_argument("kind", choices=["company", "word", "title"])
    b.add_argument("values", nargs="+")

    c = sub.add_parser("check-company", help="is this company and job real?")
    c.add_argument("company")
    c.add_argument("--title", default="", help="job title, to look for the same job on the company's own site")
    c.add_argument("--url", help="link to the job ad; its text is checked for red flags and the company website")
    c.add_argument("--text-file", help="a text file with the job ad, instead of --url")

    f = sub.add_parser("find-ats", help="find a company's careers system for the watchlist")
    f.add_argument("company")

    sub.add_parser("health", help="warn about sources that returned far fewer jobs than usual")
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0
    if args.command == "init":
        home = Path(args.config).resolve().parent
        created = init(home)
        print("Created: " + ", ".join(created) if created else "Nothing to do: config.toml and lists/ already exist.")
        print("Next: open config.toml, set your [location] and the words you care about, then run:\n"
              "  python -m jobpipe run")
        return 0
    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"Settings problem: {exc}", file=sys.stderr)
        return 2

    if args.command == "run":
        only = None
        if args.sources:
            only = [x.strip() for x in args.sources.split(",") if x.strip()]
            unknown = [x for x in only if x not in ALL_SOURCES]
            if unknown:
                print(f"Unknown source: {', '.join(unknown)}. Known: {', '.join(ALL_SOURCES)}", file=sys.stderr)
                return 2
        if args.top:
            settings.top = args.top
        runner.run(settings, only=only)
        return 0

    if args.command == "hide":
        added = add_to_list(settings, "hidden", args.links)
        print(f"Hidden {len(added)} job(s). Already hidden: {len(args.links) - len(added)}.")
        return 0

    if args.command == "block":
        kind = {"company": "companies", "word": "words", "title": "title_words"}[args.kind]
        added = add_to_list(settings, kind, args.values)
        print(f"Added {len(added)} to lists/{LIST_FILES[kind]}" + (f": {', '.join(added)}" if added else
                                                                    " (already there)"))
        print("To undo, delete the line from that file.")
        return 0

    fetcher = runner.make_fetcher(settings)

    if args.command == "check-company":
        text = ""
        if args.text_file:
            text = Path(args.text_file).read_text(encoding="utf-8", errors="replace")
        elif args.url:
            got = fetcher.page(args.url)
            text = html_to_text(got[1]) if got and got[0] < 400 else ""
            if not text:
                print("Could not read that link; checking the company name only.")
        ev = legit.check_company(fetcher, args.company, args.title, text, settings.watchlist)
        print(f"\n{ev['company']}" + (f" - {ev['title']}" if ev["title"] else ""))
        print(f"  Same job on the company's own careers page: {ev['own_posting'] or 'not found'}")
        if ev.get("domain"):
            how = "linked in the ad" if ev["domain_source"] == "posting" else "guessed from the name"
            age = ev.get("domain_age_years")
            print(f"  Website: {ev['domain']} ({how}), loads and names the company: "
                  f"{'yes' if ev.get('site_ok') else 'no'}, registered "
                  f"{f'{age} years ago' if age is not None else 'unknown'}")
        else:
            print("  Website: not found")
        print(f"  Red flags in the ad: {', '.join(ev['red_flags']) or 'none'}" if text else
              "  Red flags in the ad: not checked (give --url or --text-file)")
        print(f"\n  {ev['verdict']}")
        return 0

    if args.command == "find-ats":
        found = ats.find_ats(fetcher, args.company)
        if not found:
            print("No public careers board found. Try the exact name from the company's website, or a shorter one.")
            return 1
        print("Add one of these to config.toml:\n")
        for provider, slug, n, example in found:
            print(f"[[watchlist]]\ncompany = \"{args.company}\"\nprovider = \"{provider}\"\nslug = \"{slug}\""
                  f"\n# {n} open jobs, e.g. {example}\n")
        return 0

    if args.command == "health":
        history = settings.output_dir / "history.csv"
        days = sorted(health.load_history(history))
        if not days:
            print("No runs yet. Run `python -m jobpipe run` first.")
            return 0
        warnings = health.check(history, days[-1])
        print("\n".join(warnings) if warnings else f"All sources normal (last run {days[-1]}).")
        return 0
    return 0
