import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from jobpipe.regions import RegionRules  # noqa: E402
from jobpipe.settings import load_settings, settings_from_dict  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", default=False,
                     help="also run tests that call the real job boards")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="needs --live (calls the real job boards)")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


def load(name):
    text = (DATA / name).read_text(encoding="utf-8")
    return json.loads(text) if name.endswith(".json") else text


@pytest.fixture
def example_settings(tmp_path):
    """The shipped config.example.toml, with its home in a temporary folder."""
    s = load_settings(ROOT / "config.example.toml")
    s.home = tmp_path
    return s


@pytest.fixture
def rules(example_settings):
    return RegionRules.from_settings(example_settings)


@pytest.fixture
def bare_settings(tmp_path):
    """Settings with no filters and no scoring, for testing one thing at a time."""
    return settings_from_dict({}, tmp_path)


class FakeFetcher:
    """Answers from a dict {url substring: data}; records every URL asked for."""

    def __init__(self, answers=None, pages=None):
        self.answers = answers or {}
        self.pages = pages or {}
        self.calls = []

    def get(self, url, as_json=True, key=None, max_age_hours=None):
        self.calls.append(url)
        for part, data in self.answers.items():
            if part in url:
                if isinstance(data, Exception):
                    raise data
                return data
        raise LookupError(f"no fake answer for {url}")

    def try_get(self, url, as_json=True, key=None, max_age_hours=None):
        try:
            return self.get(url, as_json, key, max_age_hours)
        except Exception:
            return None

    def page(self, url):
        self.calls.append(url)
        for part, data in self.pages.items():
            if part in url:
                return data
        return None


@pytest.fixture
def fake_fetcher():
    return FakeFetcher
