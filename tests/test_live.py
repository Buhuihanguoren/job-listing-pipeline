"""Calls the real sources once each. Run with: python -m pytest --live

Don't run these in a loop: Remotive allows 4 calls a day."""

import re

import pytest

from jobpipe import ats, boards, hackernews
from jobpipe.http import Fetcher

pytestmark = pytest.mark.live
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@pytest.fixture
def fetcher(tmp_path):
    return Fetcher(cache_dir=tmp_path, cache_hours=0, user_agent="job-listing-pipeline tests")


@pytest.mark.parametrize("board", list(boards.FETCHERS))
def test_board_answers(board, fetcher, example_settings, rules):
    example_settings.himalayas_queries = ["data analyst"]
    example_settings.himalayas_max_pages = 1
    example_settings.jobicy_geos = ["europe"]
    rows = boards.FETCHERS[board](fetcher, example_settings, rules)
    assert rows, f"{board} returned no jobs"
    for row in rows[:20]:
        assert row["title"] and row["job_url"].startswith("http"), row
        assert row["date_posted"] == "" or DATE.match(row["date_posted"]), row


def test_hacker_news_thread(fetcher):
    thread = hackernews.latest_thread(fetcher)
    assert thread and thread[1].startswith("Ask HN: Who is hiring")


def test_watchlist_company(fetcher):
    jobs = ats.board(fetcher, "greenhouse", "gitlab")
    assert jobs and all(j["url"].startswith("https://") for j in jobs[:10])
