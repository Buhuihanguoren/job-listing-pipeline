import pytest

from jobpipe.regions import RegionRules


@pytest.mark.parametrize("text, expected", [
    ("Worldwide", True),
    ("Anywhere in the World", True),
    ("Europe, USA", True),
    ("Northern America, LATAM, Europe, APAC", True),
    ("EMEA", True),
    ("APAC, EMEA", True),
    ("Time zone: CET (+/- 3 hours)", True),
    ("Bulgaria", True),
    ("Romania, Bulgaria", True),
    ("UTC+2", True),
    ("GMT +3", True),
    ("UTC-5", False),
    ("USA", False),
    ("USA, Canada, USA timezones", False),
    ("UK", False),
    ("Germany", False),
    ("Remote - Americas", False),
    ("Japan - Remote", False),
    ("", None),
    ("Remote", None),
    ("  fully remote ", None),
    (None, None),
])
def test_region_ok(rules, text, expected):
    assert rules.region_ok(text) is expected


def test_short_words_only_match_whole_words(rules):
    # "eu" must not match inside "Leuven" or "Neuruppin"
    assert rules.region_ok("Leuven") is False
    assert rules.region_ok("Neuruppin") is False


def test_multi_word_regions_allow_any_spacing(rules):
    assert rules.region_ok("Eastern   Europe") is True


def test_timezone_lists():
    r = RegionRules([], utc_min=1, utc_max=3)
    assert r.timezones_ok([2, 3]) is True
    assert r.timezones_ok([-5, -8]) is False
    assert r.timezones_ok([]) is None
    assert r.timezones_ok(["x"]) is None


def test_onsite_places(rules):
    assert rules.onsite_ok("Sofia, Bulgaria")
    assert not rules.onsite_ok("Berlin, Germany")
    assert not RegionRules([]).onsite_ok("Sofia")


def test_labels(rules):
    assert rules.label("Europe", True) == "Remote - Europe"
    assert rules.label("", True) == "Remote"
    assert rules.label("", None) == "Remote - region unclear"
    assert rules.label("Mars", None) == "Remote - region unclear (Mars)"


def test_long_country_lists_are_shortened(rules):
    many = ", ".join(["Albania", "Austria", "Bulgaria"] + [f"Country{i}" for i in range(60)])
    assert rules.label(many, True) == "Remote - 63 countries incl. Bulgaria"
    without = ", ".join(f"Country{i}" for i in range(60))
    label = rules.label(without, False)
    assert len(label) < 150 and label.endswith("(60 countries)")
