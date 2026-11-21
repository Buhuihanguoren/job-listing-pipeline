"""Board parsers against the samples in tests/data, plus the fetchers and the cache."""

import re

import pytest
import requests

from conftest import load
from jobpipe import boards
from jobpipe.http import Fetcher

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

BOARDS = {
    # board: (parser, sample, rows, rows you may take)
    "remotive": (boards.parse_remotive, "remotive.json", 4, 2),
    "himalayas": (boards.parse_himalayas, "himalayas.json", 4, 2),
    "jobicy": (boards.parse_jobicy, "jobicy.json", 4, 2),
    "workingnomads": (boards.parse_workingnomads, "workingnomads.json", 4, 2),
    "remoteok": (boards.parse_remoteok, "remoteok.json", 4, 2),
    "weworkremotely": (boards.parse_weworkremotely, "weworkremotely.xml", 3, 2),
}


def parse(board, rules):
    parser, sample, *_ = BOARDS[board]
    return parser(load(sample), rules)


@pytest.mark.parametrize("board", BOARDS)
def test_row_count(board, rules):
    assert len(parse(board, rules)) == BOARDS[board][2]


@pytest.mark.parametrize("board", BOARDS)
def test_rows_have_required_fields(board, rules):
    for row in parse(board, rules):
        assert row["source"] == board
        assert row["title"] and row["company"] is not None
        assert row["job_url"].startswith("https://")
        assert DATE.match(row["date_posted"]), row
        assert row["location"].startswith("Remote")
        assert row["remote"] is True


@pytest.mark.parametrize("board", BOARDS)
def test_descriptions_are_plain_text(board, rules):
    for row in parse(board, rules):
        assert "<p>" not in row["description"] and "<li>" not in row["description"]
        assert "&amp;" not in row["description"] and "&lt;" not in row["description"]


@pytest.mark.parametrize("board", BOARDS)
def test_region_split(board, rules):
    assert sum(r["region_ok"] is True for r in parse(board, rules)) == BOARDS[board][3]


@pytest.mark.parametrize("board", BOARDS)
def test_rows_outside_your_region_name_the_region(board, rules):
    for row in parse(board, rules):
        if row["region_ok"] is False:
            assert row["location"] != "Remote"


def test_weworkremotely_splits_company_from_title(rules):
    rows = {r["title"]: r for r in parse("weworkremotely", rules)}
    assert rows["QA Lead"]["company"] == "Northwind Data"
    assert rows["Brand Designer"]["company"] == ""


def test_remoteok_skips_the_legal_notice(rules):
    raw = load("remoteok.json")
    assert "legal" in raw[0]
    assert all(r["title"] for r in boards.parse_remoteok(raw, rules))


def test_remoteok_repairs_broken_accents(rules):
    rows = parse("remoteok", rules)
    text = " ".join(r["company"] + r["location"] + r["description"] for r in rows)
    assert "Ã" not in text
    assert "Globex México" in {r["company"] for r in rows}


def test_himalayas_country_and_timezone_rules(rules):
    rows = {r["title"]: r for r in parse("himalayas", rules)}
    assert rows["Ads Quality Rater"]["region_ok"] is True
    assert rows["AI Data Quality Reviewer"]["location"] == "Remote - Worldwide"
    assert rows["Timezone test: Americas hours only"]["region_ok"] is False
    assert rows["Compliance Analyst"]["region_ok"] is False


def test_unclear_region_is_kept_and_labelled(rules):
    unclear = [r for r in parse("remoteok", rules) if r["region_ok"] is None]
    assert unclear and all("region unclear" in r["location"] for r in unclear)


def test_salary_text_survives_html_cleanup(rules):
    first = parse("remotive", rules)[0]
    assert "€2,000 - 2,500" in first["description"]


@pytest.mark.parametrize("value, expected", [
    (1794497895, "2026-11-12"),
    ("1794497895", "2026-11-12"),
    ("2026-11-18T10:00:00", "2026-11-18"),
    ("Wed, 18 Nov 2026 10:00:00 +0000", "2026-11-18"),
    ("", ""),
    ("not a date", ""),
])
def test_iso_date(value, expected):
    assert boards.iso_date(value) == expected


# fetchers, with a fake network
def test_fetchers_use_the_board_apis(rules, example_settings, fake_fetcher, monkeypatch):
    monkeypatch.setattr(boards, "pause", lambda seconds: None)
    f = fake_fetcher({"remotive.com": load("remotive.json"), "remoteok.com": load("remoteok.json"),
                      "jobicy.com": load("jobicy.json"), "workingnomads.com": load("workingnomads.json"),
                      "weworkremotely.com": load("weworkremotely.xml"), "himalayas.app": load("himalayas.json")})
    example_settings.himalayas_queries = ["qa"]
    for name, fetch in boards.FETCHERS.items():
        assert fetch(f, example_settings, rules), name
    assert any("country=Bulgaria" in u for u in f.calls)
    assert sum("jobicy.com" in u for u in f.calls) == len(example_settings.jobicy_geos)


def test_himalayas_rate_limit_keeps_rows_and_stops_paging(rules, example_settings, monkeypatch):
    calls = []

    class Busy:
        status_code = 429

    class Network:
        def get(self, url, as_json=True, key=None, max_age_hours=None):
            calls.append(url)
            if "q=qa" in url and "page=2" in url:
                raise requests.HTTPError(response=Busy())
            return {"totalCount": 100, "jobs": [{"title": "t", "companyName": "c", "applicationLink": f"https://x/{len(calls)}",
                                                 "pubDate": 1794497895, "locationRestrictions": []}]}

    monkeypatch.setattr(boards, "pause", lambda seconds: None)
    example_settings.himalayas_queries = ["qa", "data"]
    rows = boards.fetch_himalayas(Network(), example_settings, rules)
    assert len(rows) == 2                                          # page 1 of both queries
    assert not any("q=data" in u and "page=2" in u for u in calls)  # no paging after the 429


# cache
class _Response:
    status_code = 200

    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data

    @property
    def text(self):
        return str(self.data)


def test_cache_avoids_a_second_request(tmp_path):
    f = Fetcher(cache_dir=tmp_path, cache_hours=6)
    calls = []
    f.session.get = lambda url, timeout: calls.append(url) or _Response({"jobs": []})
    f.get("https://example.invalid/a")
    f.get("https://example.invalid/a")
    assert len(calls) == 1


def test_cache_can_be_turned_off(tmp_path):
    f = Fetcher(cache_dir=tmp_path, cache_hours=0)
    calls = []
    f.session.get = lambda url, timeout: calls.append(url) or _Response({"jobs": []})
    f.get("https://example.invalid/b")
    f.get("https://example.invalid/b")
    assert len(calls) == 2


def test_try_get_returns_none_on_errors(tmp_path):
    f = Fetcher(cache_dir=tmp_path)
    f.retry_pause = 0

    def boom(url, timeout):
        raise requests.ConnectionError("down")

    f.session.get = boom
    assert f.try_get("https://example.invalid/c") is None


def test_one_network_hiccup_is_retried(tmp_path):
    f = Fetcher(cache_dir=tmp_path)
    f.retry_pause = 0
    answers = [requests.ConnectionError("reset"), _Response({"jobs": [1]})]

    def flaky(url, timeout):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    f.session.get = flaky
    assert f.get("https://example.invalid/d") == {"jobs": [1]}
