from datetime import date

import pandas as pd
import pytest

from jobpipe import pipeline as pl
from jobpipe.settings import Lists

TODAY = date(2026, 11, 21)


def job(title, company="Acme", url=None, description="", location="Remote - Europe", posted="2026-11-20",
        region_ok=True, remote=True, source="remotive"):
    return {"source": source, "title": title, "company": company, "location": location,
            "job_url": url or f"https://jobs.example/{abs(hash((title, company, description))) % 10**8}",
            "date_posted": posted, "description": description, "remote": remote, "region_ok": region_ok}


def run(rows, settings, lists=None, seen=None):
    return pl.process(pd.DataFrame(rows), settings, lists or Lists(), seen or set(), TODAY)


# word matching
@pytest.mark.parametrize("word, text, hit", [
    ("qa", "Junior QA Engineer", True),
    ("qa", "Qatar office manager", False),
    ("ai", "AI Trainer", True),
    ("ai", "Maintenance Technician", False),
    ("test*", "Software Tester", True),
    ("test*", "Testing Lead", True),
    ("test", "Software Tester", False),
    ("head of", "Head  of QA", True),
    ("sr.", "Sr. Data Analyst", True),
    ("c++", "C++ Developer", True),
    ("одит*", "Одитор, вътрешен контрол", True),
])
def test_word_pattern(word, text, hit):
    assert bool(pl.word_pattern(word).search(text)) is hit


# duplicates
def test_dedup_keeps_junior_next_to_senior(bare_settings):
    rows = [job("Junior QA Engineer", description="short"),
            job("Senior QA Engineer", description="much longer description " * 5),
            job("QA Engineer (m/f/d)", description="x", source="himalayas"),
            job("QA Engineer", description="xy", source="jobicy")]
    titles = set(run(rows, bare_settings).jobs["title"])
    assert {"Junior QA Engineer", "Senior QA Engineer"} <= titles
    assert len(titles & {"QA Engineer (m/f/d)", "QA Engineer"}) == 1


def test_dedup_keeps_the_longest_description(bare_settings):
    rows = [job("Data Analyst", description="short", source="remotive"),
            job("Data Analyst", description="a much longer and more useful description", source="jobicy")]
    result = run(rows, bare_settings)
    assert result.duplicates == 1
    assert result.jobs.iloc[0]["source"] == "jobicy"


def test_same_ad_under_two_company_names_is_merged(bare_settings):
    text = "We are hiring a QA analyst to own regression testing across web and mobile. " * 4
    rows = [job("QA Analyst", company="Talent Agency", description=text),
            job("QA Analyst", company="Real Client Ltd", description=text)]
    assert len(run(rows, bare_settings).jobs) == 1


def test_short_shared_text_is_not_merged(bare_settings):
    rows = [job("QA Analyst", company="One", description="Apply now."),
            job("QA Analyst", company="Two", description="Apply now.")]
    assert len(run(rows, bare_settings).jobs) == 2


# filters
def test_every_drop_has_a_reason(bare_settings):
    bare_settings.title_must_contain = ["qa", "analyst*"]
    bare_settings.max_age_days = 30
    lists = Lists(companies=["acme recruiting"], title_words=["senior"], words=["commission only"],
                  hidden={"https://jobs.example/hidden"})
    rows = [
        job("QA Engineer", url="https://jobs.example/hidden?utm_source=newsletter"),
        job("QA Engineer", company="Elsewhere", region_ok=False),
        job("QA Tester", company="ACME Recruiting Ltd"),
        job("Senior QA Analyst", company="Fine Co"),
        job("Data Analyst", company="Fine Co 2", description="Pay is commission only."),
        job("Product Designer", company="Fine Co 3"),
        job("QA Analyst", company="Old Co", posted="2026-09-01"),
        job("Junior QA Analyst", company="Good Co"),
    ]
    result = run(rows, bare_settings, lists)
    assert list(result.jobs["title"]) == ["Junior QA Analyst"]
    assert result.reasons == {"hidden by you": 1, "outside your region": 1, "blocked company": 1,
                              "blocked title word": 1, "blocked word": 1, "title doesn't match": 1, "too old": 1}
    assert set(result.dropped["reason"]) == set(result.reasons)


def test_unclear_region_is_kept(bare_settings):
    result = run([job("QA Engineer", region_ok=None, location="Remote - region unclear")], bare_settings)
    assert len(result.jobs) == 1


def test_rows_without_title_or_link_are_ignored(bare_settings):
    rows = [job(""), {**job("QA"), "job_url": ""}, job("Real job")]
    assert list(run(rows, bare_settings).jobs["title"]) == ["Real job"]


def test_empty_input(bare_settings):
    result = run([], bare_settings)
    assert result.jobs.empty and result.raw_count == 0 and result.new_count == 0


# scoring
def test_scoring_adds_up_and_explains_itself(bare_settings):
    bare_settings.title_points = {"junior": 15, "qa": 20, "senior": -25}
    bare_settings.description_points = {"python": 3}
    bare_settings.remote_points, bare_settings.pay_points = 5, 10
    rows = [job("Junior QA Engineer", company="A", description="Python and pytest. Salary €2,000 - 2,500."),
            job("Senior QA Engineer", company="B", remote=False)]
    jobs = run(rows, bare_settings).jobs.set_index("title")
    assert jobs.loc["Junior QA Engineer", "score"] == 15 + 20 + 3 + 5 + 10
    assert jobs.loc["Junior QA Engineer", "why"] == "+15 junior, +20 qa, +3 python, +5 remote, +10 salary stated"
    assert jobs.loc["Junior QA Engineer", "pay"] == "€2,000 - 2,500"
    assert jobs.loc["Senior QA Engineer", "score"] == -5
    assert list(run(rows, bare_settings).jobs["title"])[0] == "Junior QA Engineer"   # best first


@pytest.mark.parametrize("text, found", [
    ("Salary: €2,000 - 2,500 a month", "€2,000 - 2,500"),
    ("we pay 45k EUR a year", "45k EUR"),
    ("Compensation $120,000 to $140,000", "$120,000 to $140,000"),
    ("3500 BGN gross", "3500 BGN"),
    ("$30/hour, flexible", "$30/hour"),
    ("Заплата от 920 до 1943 € бруто", "1943 €"),
    ("2,000 happy users", ""),
    ("ISO 27001 and SOC 2", ""),
    ("we are about to hit $100M in revenue", ""),
    ("a €500 home office budget", ""),
    ("Series B: raised $40 million. Salary: up to €3,000 per month", "€3,000"),
])
def test_pay_hint(text, found):
    assert pl.pay_hint(text) == found


# new since last run
def test_new_flag_uses_seen_links(bare_settings):
    rows = [job("QA One", url="https://jobs.example/1"), job("QA Two", url="https://jobs.example/2")]
    result = run(rows, bare_settings, seen={"https://jobs.example/1"})
    new = dict(zip(result.jobs["title"], result.jobs["new"]))
    assert new == {"QA One": False, "QA Two": True}
    assert result.new_count == 1
