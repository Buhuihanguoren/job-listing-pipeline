"""The commands, end to end, with fake sources."""

from datetime import date

import pandas as pd
import pytest

from conftest import ROOT, load
from jobpipe import boards, cli, runner
from jobpipe.settings import load_settings


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    return tmp_path


def test_init_then_help(home, capsys):
    assert (home / "config.toml").exists() and (home / "lists" / "hidden_jobs.txt").exists()
    assert cli.main([]) == 0
    assert "check-company" in capsys.readouterr().out


def test_missing_config_is_a_clear_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["run"]) == 2
    assert "jobpipe init" in capsys.readouterr().err


def test_unknown_source_is_rejected(home, capsys):
    assert cli.main(["run", "--sources", "remotive,monster"]) == 2
    assert "monster" in capsys.readouterr().err


def test_hide_and_block(home, capsys):
    assert cli.main(["hide", "https://jobs.example/1?utm_source=x", "https://jobs.example/1"]) == 0
    assert "Hidden 1 job" in capsys.readouterr().out
    assert cli.main(["block", "company", "Acme Recruiting"]) == 0
    assert cli.main(["block", "title", "principal"]) == 0          # already in the example list
    out = capsys.readouterr().out
    assert "Acme Recruiting" in out and "already there" in out
    companies = (home / "lists" / "block_companies.txt").read_text(encoding="utf-8")
    assert companies.rstrip().endswith("Acme Recruiting")


def _fake_sources(monkeypatch, rules_rows):
    """Replace every source with the offline samples."""
    def board(name, sample, parser):
        return lambda fetcher, settings, rules: parser(load(sample), rules)
    fake = {
        "remotive": board("remotive", "remotive.json", boards.parse_remotive),
        "remoteok": board("remoteok", "remoteok.json", boards.parse_remoteok),
        "jobicy": board("jobicy", "jobicy.json", boards.parse_jobicy),
        "himalayas": board("himalayas", "himalayas.json", boards.parse_himalayas),
        "weworkremotely": board("weworkremotely", "weworkremotely.xml", boards.parse_weworkremotely),
        "workingnomads": board("workingnomads", "workingnomads.json", boards.parse_workingnomads),
        "hackernews": lambda f, s, r: (_ for _ in ()).throw(TimeoutError("read timed out")),
        "watchlist": lambda f, s, r: rules_rows,
    }
    monkeypatch.setattr(runner, "SOURCES", fake)


def test_full_run_writes_report_and_remembers_jobs(home, monkeypatch, capsys):
    _fake_sources(monkeypatch, [])
    settings = load_settings(home / "config.toml")
    settings.max_age_days = 0
    result, paths = runner.run(settings, today=date(2026, 11, 21), fetcher=object())

    out = capsys.readouterr().out
    assert "Failed sources: hackernews (TimeoutError: read timed out)" in out
    assert paths["report"].exists() and paths["jobs"].exists() and paths["dropped"].exists()
    jobs = pd.read_csv(paths["jobs"], encoding="utf-8-sig")
    assert len(jobs) == len(result.jobs) > 0
    assert list(jobs["score"]) == sorted(jobs["score"], reverse=True)
    assert "Senior" not in " ".join(jobs["title"])
    report = paths["report"].read_text(encoding="utf-8")
    assert "| hackernews | 0 | failed: TimeoutError" in report
    assert "outside your region" in report
    dropped = pd.read_csv(paths["dropped"], encoding="utf-8-sig")
    assert "outside your region" in set(dropped["reason"])

    # second run: same jobs, nothing new; the hidden one disappears
    first = result.jobs.iloc[0]["job_url"]
    assert cli.main(["hide", first]) == 0
    result2, _ = runner.run(load_settings(home / "config.toml"), today=date(2026, 11, 21), fetcher=object(),
                            quiet=True)
    assert result2.new_count == 0
    assert first not in set(result2.jobs["job_url"])
    assert result2.reasons.get("hidden by you") == 1


def test_example_config_ranks_the_samples_sensibly(home, monkeypatch):
    _fake_sources(monkeypatch, [])
    settings = load_settings(home / "config.toml")
    settings.max_age_days = 0
    result, _ = runner.run(settings, today=date(2026, 11, 21), fetcher=object(), quiet=True)
    top = result.jobs.iloc[0]
    assert top["title"] == "Junior QA Engineer" and top["pay"] == "€2,000 - 2,500"
    assert "+15 junior" in top["why"] and "+10 salary stated" in top["why"]
