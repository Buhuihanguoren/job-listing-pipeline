"""Company check and source health check."""

from jobpipe import health, legit


# red flags
def test_red_flags():
    hits = legit.red_flag_hits("Please contact us on Telegram and pay the training fee")
    assert "training fee" in hits and any("telegram" in h for h in hits)
    assert legit.red_flag_hits("Competitive salary, remote, great team") == []


def test_messenger_apps_only_count_as_a_hiring_channel():
    assert legit.red_flag_hits("Answer customers by phone, chat, WhatsApp and Telegram.") == []
    assert legit.red_flag_hits("Please contact our recruiter on Telegram for the interview.")
    assert legit.red_flag_hits("Interviews are held via WhatsApp only.")


def test_anti_scam_notices_are_not_flagged():
    assert legit.red_flag_hits("We will never ask for a training fee or interview you on Telegram.") == []


def test_registrable_domain():
    assert legit.registrable("www.jobs.example.com") == "example.com"
    assert legit.registrable("shop.example.co.uk") == "example.co.uk"


# own posting, website
def _board(jobs):
    return lambda fetcher, provider, slug: jobs.get(f"{provider}/{slug}", [])


def test_own_posting_prefers_the_exact_title(monkeypatch):
    monkeypatch.setattr(legit, "board", _board({"lever/acme": [
        {"title": "QA Engineer", "url": "https://jobs.lever.co/acme/a", "apply_url": "", "location": "", "description": ""},
        {"title": "QA Engineer Intern", "url": "https://jobs.lever.co/acme/b", "apply_url": "", "location": "",
         "description": ""},
    ]}))
    own = legit.find_own_posting(None, "Acme", "QA Engineer Intern")
    assert own["url"] == "https://jobs.lever.co/acme/b" and own["provider"] == "lever"


def test_own_posting_none_when_titles_differ(monkeypatch):
    monkeypatch.setattr(legit, "board", lambda f, p, s: [
        {"title": "Senior Backend Engineer", "url": "u", "apply_url": "", "location": "", "description": ""}])
    assert legit.find_own_posting(None, "Acme", "QA Tester") is None


def test_ats_slug_is_read_from_the_ad(monkeypatch):
    asked = []
    monkeypatch.setattr(legit, "board", lambda f, provider, slug: asked.append((provider, slug)) or [])
    legit.find_own_posting(None, "Totally Different Name", "QA", "Apply: https://job-boards.greenhouse.io/realslug/jobs/1")
    assert ("greenhouse", "realslug") in asked


def test_watchlist_slug_is_used_for_long_legal_names(monkeypatch):
    asked = []
    monkeypatch.setattr(legit, "board", lambda f, provider, slug: asked.append((provider, slug)) or [])
    watch = [{"company": "Globex Corporation", "provider": "ashby", "slug": "globexhq"}]
    legit.find_own_posting(None, "Globex Holdings Europe S.A.", "QA", "", watch)
    assert ("ashby", "globexhq") in asked


def test_domain_from_the_ad_beats_guessing(fake_fetcher):
    f = fake_fetcher(pages={"acmesoft.io": (200, "<title>Acmesoft</title> acmesoft builds tools")})
    text = "More at https://www.acmesoft.io/careers or jobs@acmesoft.io. Also https://linkedin.com/company/acme"
    assert legit.find_domain(f, "Acmesoft", text) == ("acmesoft.io", "posting")
    assert f.calls == []                     # nothing guessed, nothing fetched


def test_guessed_domain_must_name_the_company(fake_fetcher):
    f = fake_fetcher(pages={"globexlabs.com": (200, "<title>Parked domain</title> buy this domain"),
                            "globexlabs.io": (200, "<title>Globex Labs</title> globex labs, data tools")})
    assert legit.find_domain(f, "Globex Labs", "") == ("globexlabs.io", "guess")


def test_domain_age_from_rdap(fake_fetcher):
    f = fake_fetcher({"data.iana.org": {"services": [[["io", "ai"], ["https://rdap.example/io/"]]]},
                      "rdap.example/io/domain/acmesoft.io": {"events": [
                          {"eventAction": "registration", "eventDate": "2015-03-01T00:00:00Z"}]}})
    age = legit.domain_age_years(f, "careers.acmesoft.io")
    assert age is not None and age > 10


def test_verdicts():
    base = {"red_flags": [], "own_posting": None, "domain": None, "domain_source": "", "site_ok": False}
    assert legit.verdict({**base, "red_flags": ["training fee"]}).startswith("Red flags")
    assert legit.verdict({**base, "own_posting": "https://x"}).startswith("Looks real")
    assert legit.verdict({**base, "domain": "a.io", "domain_source": "posting", "site_ok": True,
                          "domain_age_years": 6}).startswith("Probably real")
    assert legit.verdict({**base, "domain": "a.io", "domain_source": "guess", "site_ok": True,
                          "domain_age_years": 6}).startswith("Not confirmed")


# health
def test_health_flags_a_dead_source():
    earlier = {f"2026-11-{d:02d}": {"remotive": 300, "jobicy": 90} for d in range(10, 17)}
    warnings = health.alerts({"remotive": 0, "jobicy": 95}, earlier)
    assert len(warnings) == 1 and warnings[0].startswith("remotive: 0 listings")


def test_health_needs_some_history():
    assert health.alerts({"remotive": 0}, {"2026-11-10": {"remotive": 300}}) == []


def test_health_ignores_small_sources():
    earlier = {f"2026-11-{d:02d}": {"hackernews": 3} for d in range(10, 17)}
    assert health.alerts({"hackernews": 0}, earlier) == []


def test_history_file_round_trip(tmp_path):
    path = tmp_path / "history.csv"
    health.append_history(path, "2026-11-19", {"remotive": 10}, {})
    health.append_history(path, "2026-11-20", {"remotive": 12, "jobicy": 0}, {"jobicy": "timeout"})
    health.append_history(path, "2026-11-20", {"remotive": 14}, {})          # second run that day wins
    assert health.load_history(path) == {"2026-11-19": {"remotive": 10}, "2026-11-20": {"remotive": 14, "jobicy": 0}}
    assert health.check(path, "2026-11-21", {"remotive": 0}) == [
        "remotive: 0 listings this run, usually about 12. The site may have changed or be blocking requests."]
