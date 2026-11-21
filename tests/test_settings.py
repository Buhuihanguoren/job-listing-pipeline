import pytest

from conftest import ROOT
from jobpipe.settings import (ALL_SOURCES, LIST_FILES, ConfigError, add_to_list, init, load_lists, load_settings,
                              norm_url, read_list, settings_from_dict)


def test_example_config_is_valid():
    s = load_settings(ROOT / "config.example.toml")
    assert s.enabled_sources() == list(ALL_SOURCES)
    assert s.watchlist and all(w["provider"] and w["slug"] for w in s.watchlist)
    assert s.title_points["qa"] > 0 > s.title_points["senior"]
    assert "europe" in s.accept_regions


def test_missing_config_explains_what_to_do(tmp_path):
    with pytest.raises(ConfigError, match="jobpipe init"):
        load_settings(tmp_path / "config.toml")


def test_typo_in_toml_is_reported(tmp_path):
    bad = tmp_path / "config.toml"
    bad.write_text("[location\ncountry = 'x'\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="typo"):
        load_settings(bad)


@pytest.mark.parametrize("raw, message", [
    ({"sources": {"linkedin": True}}, "unknown source"),
    ({"filters": {"max_age_days": "thirty"}}, "whole number"),
    ({"filters": {"title_must_contain": "qa"}}, "list of words"),
    ({"sources": {"remotive": "yes"}}, "true or false"),
    ({"scoring": {"title": {"qa": "high"}}}, "whole number of points"),
    ({"location": {"utc_offset_min": 5, "utc_offset_max": 1}}, "larger"),
    ({"watchlist": [{"company": "X", "provider": "myspace", "slug": "x"}]}, "unknown provider"),
    ({"watchlist": [{"company": "X", "provider": "lever"}]}, "missing: slug"),
])
def test_wrong_values_give_readable_errors(tmp_path, raw, message):
    with pytest.raises(ConfigError, match=message):
        settings_from_dict(raw, tmp_path)


def test_sources_can_be_switched_off(tmp_path):
    s = settings_from_dict({"sources": {"remoteok": False, "hackernews": False}}, tmp_path)
    assert "remoteok" not in s.enabled_sources() and "remotive" in s.enabled_sources()


def test_integer_offsets_are_accepted(tmp_path):
    s = settings_from_dict({"location": {"utc_offset_min": 1, "utc_offset_max": 3}}, tmp_path)
    assert (s.utc_offset_min, s.utc_offset_max) == (1.0, 3.0)


# lists
def test_init_creates_config_and_lists_once(tmp_path):
    created = init(tmp_path)
    assert "config.toml" in created and len(created) == 1 + len(LIST_FILES)
    (tmp_path / "config.toml").write_text("# my edits\n", encoding="utf-8")
    assert init(tmp_path) == []
    assert (tmp_path / "config.toml").read_text(encoding="utf-8") == "# my edits\n"    # never overwritten


def test_lists_ignore_comments_and_blank_lines(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("# comment\n\nAcme Recruiting\n  Globex  \n", encoding="utf-8")
    assert read_list(path) == ["Acme Recruiting", "Globex"]
    assert read_list(tmp_path / "missing.txt") == []


def test_example_lists_load(example_settings):
    init(example_settings.home)
    lists = load_lists(example_settings)
    assert "senior" in lists.title_words and "commission only" in lists.words
    assert lists.companies == [] and lists.hidden == set()


def test_add_to_list_skips_duplicates(example_settings):
    init(example_settings.home)
    assert add_to_list(example_settings, "companies", ["Acme Recruiting", "acme recruiting", "Globex"]) == \
        ["Acme Recruiting", "Globex"]
    assert add_to_list(example_settings, "companies", ["ACME RECRUITING"]) == []
    assert load_lists(example_settings).companies == ["acme recruiting", "globex"]


def test_hidden_links_match_without_tracking_parameters(example_settings):
    add_to_list(example_settings, "hidden", ["https://jobs.example/qa-123?utm_source=mail&ref=x"])
    assert add_to_list(example_settings, "hidden", ["https://jobs.example/qa-123/"]) == []
    assert norm_url("https://jobs.example/qa-123/") in load_lists(example_settings).hidden


def test_norm_url_keeps_the_job_id():
    a = norm_url("https://news.ycombinator.com/item?id=1")
    b = norm_url("https://news.ycombinator.com/item?id=2")
    assert a != b
    assert norm_url("HTTPS://Example.com/Jobs/1/?utm_campaign=x") == "https://example.com/jobs/1"
