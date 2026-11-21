"""Company career pages and Hacker News."""

from jobpipe import ats, hackernews as hn

GREENHOUSE = {"jobs": [
    {"title": "QA Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
     "location": {"name": "Remote - EMEA"}, "content": "&lt;p&gt;Test &amp;amp; automate&lt;/p&gt;"},
    {"title": "Account Executive", "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
     "location": {"name": "Remote - US"}, "content": ""},
    {"title": "Data Analyst", "absolute_url": "https://boards.greenhouse.io/acme/jobs/3",
     "location": {"name": "Sofia, Bulgaria"}, "content": "<p>SQL</p>"},
    {"title": "Designer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/4",
     "location": {"name": "Berlin"}, "content": ""},
    {"title": "Support Specialist", "absolute_url": "https://boards.greenhouse.io/acme/jobs/5",
     "location": {"name": "Remote"}, "content": ""},
]}


def test_provider_parsers_share_one_shape():
    samples = {
        "greenhouse": GREENHOUSE,
        "lever": [{"text": "QA", "hostedUrl": "https://jobs.lever.co/x/1", "applyUrl": "https://jobs.lever.co/x/1/apply",
                   "categories": {"location": "Remote"}, "descriptionPlain": "About",
                   "lists": [{"text": "You have", "content": "<li>Python</li>"}], "additionalPlain": "Benefits"}],
        "ashby": {"jobs": [{"title": "QA", "jobUrl": "https://jobs.ashbyhq.com/x/1", "applyUrl": "u",
                            "location": "Remote", "descriptionPlain": "About"}]},
        "workable": {"jobs": [{"title": "QA", "url": "https://apply.workable.com/x/j/1", "city": "Sofia",
                               "country": "Bulgaria", "description": "<p>About</p>"}]},
        "smartrecruiters": {"content": [{"name": "QA", "id": "1", "company": {"identifier": "X"},
                                         "location": {"city": "Sofia", "country": "bg", "remote": True}}]},
        "recruitee": {"offers": [{"title": "QA", "careers_url": "https://x.recruitee.com/o/qa",
                                  "careers_apply_url": "u", "location": "Remote", "description": "<p>A</p>",
                                  "requirements": "<p>B</p>"}]},
    }
    for provider, data in samples.items():
        jobs = ats.PROVIDERS[provider][1](data)
        assert jobs, provider
        for j in jobs:
            assert set(j) == {"title", "url", "apply_url", "location", "description"}, provider
            assert j["title"] and j["url"].startswith("https://")
            assert "<p>" not in j["description"] and "<li>" not in j["description"]
    lever = ats.PROVIDERS["lever"][1](samples["lever"])[0]
    assert "You have: Python" in lever["description"]


def test_keep_job_by_region(rules):
    assert ats.keep_job({"location": "Remote - EMEA", "title": "QA"}, rules) == ("Remote - EMEA", True, True)
    assert ats.keep_job({"location": "Remote - US", "title": "QA"}, rules)[2] is False
    assert ats.keep_job({"location": "Sofia, Bulgaria", "title": "QA"}, rules) == ("Sofia, Bulgaria", False, True)
    assert ats.keep_job({"location": "Berlin", "title": "QA"}, rules)[2] is False
    label, remote, ok = ats.keep_job({"location": "Remote", "title": "QA"}, rules)
    assert remote and ok is None and "region unclear" in label


def test_watchlist_reads_each_company(rules, example_settings, fake_fetcher):
    example_settings.watchlist = [{"company": "Acme", "provider": "greenhouse", "slug": "acme"}]
    rows = ats.fetch_watchlist(fake_fetcher({"greenhouse.io/v1/boards/acme": GREENHOUSE}), example_settings, rules)
    assert len(rows) == 5 and all(r["company"] == "Acme" and r["source"] == "watchlist" for r in rows)
    ok = {r["title"]: r["region_ok"] for r in rows}
    assert ok == {"QA Engineer": True, "Account Executive": False, "Data Analyst": True, "Designer": False,
                  "Support Specialist": None}
    assert "Test & automate" in rows[0]["description"]


def test_missing_board_is_empty_not_an_error(fake_fetcher):
    assert ats.board(fake_fetcher({}), "lever", "nobody") == []


def test_slug_variants():
    assert ats.slug_variants("Acme Data Technologies Ltd.") == ["acmedata", "acme-data", "acme"]
    assert ats.slug_variants("Globex") == ["globex"]
    assert ats.slug_variants("Ltd.") == []


def test_find_ats(fake_fetcher):
    f = fake_fetcher({"boards/globex/": GREENHOUSE})
    found = ats.find_ats(f, "Globex")
    assert found == [("greenhouse", "globex", 5, "QA Engineer")]


# Hacker News
def test_hn_post_parsing(rules):
    row = hn.parse_post(123, "Acme AI | QA Engineer | REMOTE (Europe) | Full-time\nWe build things.", rules)
    assert row["company"] == "Acme AI" and row["title"] == "QA Engineer"
    assert row["location"] == "Remote - Europe" and row["job_url"].endswith("id=123")


def test_hn_drops_us_only_and_onsite_posts(rules):
    assert hn.parse_post(1, "Foo | Engineer | REMOTE (US only)\nx", rules) is None
    assert hn.parse_post(2, "Bar | Engineer | Onsite Berlin\nx", rules) is None
    assert hn.parse_post(3, "Baz | Engineer | REMOTE\nno region given", rules) is None
    assert hn.parse_post(4, "Qux | QA | REMOTE (US only, or Europe for contractors)\nx", rules) is not None


def test_hn_comment_html_is_cleaned():
    text = hn.comment_text("Acme | QA | REMOTE (EU)<p>We use <a href=\"x\">pytest</a> &amp; Python")
    assert text == "Acme | QA | REMOTE (EU)\nWe use  pytest  & Python"


def test_hn_fetch_reads_the_latest_thread(rules, example_settings, fake_fetcher):
    f = fake_fetcher({
        "search_by_date": {"hits": [{"title": "Ask HN: Who wants to be hired? (November 2026)", "objectID": "1"},
                                    {"title": "Ask HN: Who is hiring? (November 2026)", "objectID": "42"}]},
        "items/42": {"children": [
            {"id": 7, "created_at": "2026-11-02T10:00:00Z", "text": "Acme | QA Engineer | REMOTE (EMEA)<p>Details"},
            {"id": 8, "created_at": "2026-11-02T11:00:00Z", "text": "Globex | Developer | Onsite NYC"},
            {"id": 9, "created_at": "2026-11-02T12:00:00Z", "text": None},
        ]},
    })
    rows = hn.fetch_hackernews(f, example_settings, rules)
    assert [r["job_url"] for r in rows] == ["https://news.ycombinator.com/item?id=7"]
    assert rows[0]["date_posted"] == "2026-11-02"
