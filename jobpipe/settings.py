"""config.toml and the text lists in lists/."""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

if sys.version_info >= (3, 11):
    import tomllib
else:  # Python 3.10
    import tomli as tomllib

REPO_DIR = Path(__file__).resolve().parent.parent
EXAMPLE_CONFIG = REPO_DIR / "config.example.toml"
EXAMPLE_LISTS = REPO_DIR / "lists.example"

LIST_FILES = {
    "companies": "block_companies.txt",
    "title_words": "block_title_words.txt",
    "words": "block_words.txt",
    "hidden": "hidden_jobs.txt",
}

BOARD_SOURCES = ("remotive", "remoteok", "jobicy", "himalayas", "weworkremotely", "workingnomads")
ALL_SOURCES = BOARD_SOURCES + ("hackernews", "watchlist")
PROVIDERS = ("greenhouse", "lever", "lever_eu", "ashby", "workable", "smartrecruiters", "recruitee")


class ConfigError(ValueError):
    """config.toml is missing, unreadable, or has a wrong value."""


@dataclass
class Settings:
    home: Path                       # folder with config.toml, lists/ and output/
    country: str = ""
    accept_regions: list[str] = field(default_factory=list)
    utc_offset_min: float = -12
    utc_offset_max: float = 14
    onsite_places: list[str] = field(default_factory=list)
    sources: dict[str, bool] = field(default_factory=lambda: {s: True for s in ALL_SOURCES})
    cache_hours: float = 6
    himalayas_queries: list[str] = field(default_factory=list)
    himalayas_max_pages: int = 3
    jobicy_geos: list[str] = field(default_factory=lambda: ["europe"])
    user_agent: str = "job-listing-pipeline"
    title_must_contain: list[str] = field(default_factory=list)
    max_age_days: int = 0
    title_points: dict[str, int] = field(default_factory=dict)
    description_points: dict[str, int] = field(default_factory=dict)
    remote_points: int = 0
    pay_points: int = 0
    output_folder: str = "output"
    top: int = 25
    watchlist: list[dict] = field(default_factory=list)

    @property
    def output_dir(self) -> Path:
        return self.home / self.output_folder

    @property
    def lists_dir(self) -> Path:
        return self.home / "lists"

    @property
    def cache_dir(self) -> Path:
        return self.home / ".cache"

    def enabled_sources(self) -> list[str]:
        return [s for s in ALL_SOURCES if self.sources.get(s)]


# config.toml
def load_settings(path: str | Path = "config.toml") -> Settings:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"{path} not found. Run `python -m jobpipe init` first, then edit config.toml.")
    try:
        with open(path, "rb") as fh:
            raw = tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path.name} has a typo: {exc}") from exc
    return settings_from_dict(raw, path.resolve().parent)


def _table(parent: dict, key: str, label: str | None = None) -> dict:
    value = parent.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{label or key}] should be a section, not a single value")
    return value


def _value(table: dict, key: str, kind, default, section: str):
    if key not in table:
        return default
    value = table[key]
    if kind is float and isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    if kind is list:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ConfigError(f"[{section}] {key} should be a list of words in quotes, like [\"qa\", \"data\"]")
        return [v.strip() for v in value if v.strip()]
    if kind is bool and not isinstance(value, bool):
        raise ConfigError(f"[{section}] {key} should be true or false")
    if kind is int and (not isinstance(value, int) or isinstance(value, bool)):
        raise ConfigError(f"[{section}] {key} should be a whole number, got {value!r}")
    if kind is float and not isinstance(value, float):
        raise ConfigError(f"[{section}] {key} should be a number, got {value!r}")
    if kind is str and not isinstance(value, str):
        raise ConfigError(f"[{section}] {key} should be text in quotes, got {value!r}")
    return value


def _points(table: dict, section: str) -> dict[str, int]:
    out = {}
    for word, pts in table.items():
        if not isinstance(pts, int) or isinstance(pts, bool):
            raise ConfigError(f"[{section}] \"{word}\" should be a whole number of points, got {pts!r}")
        if word.strip():
            out[word.strip().lower()] = pts
    return out


def settings_from_dict(raw: dict, home: Path) -> Settings:
    s = Settings(home=Path(home))

    loc = _table(raw, "location")
    s.country = _value(loc, "country", str, s.country, "location")
    s.accept_regions = [w.lower() for w in _value(loc, "accept_regions", list, s.accept_regions, "location")]
    s.utc_offset_min = _value(loc, "utc_offset_min", float, s.utc_offset_min, "location")
    s.utc_offset_max = _value(loc, "utc_offset_max", float, s.utc_offset_max, "location")
    s.onsite_places = [w.lower() for w in _value(loc, "onsite_places", list, s.onsite_places, "location")]
    if s.utc_offset_min > s.utc_offset_max:
        raise ConfigError("[location] utc_offset_min is larger than utc_offset_max")

    src = _table(raw, "sources")
    for key, value in src.items():
        if key == "options":
            continue
        if key not in ALL_SOURCES:
            raise ConfigError(f"[sources] unknown source \"{key}\". Known sources: {', '.join(ALL_SOURCES)}")
        s.sources[key] = _value(src, key, bool, True, "sources")
    opt = _table(src, "options", "sources.options")
    s.cache_hours = _value(opt, "cache_hours", float, s.cache_hours, "sources.options")
    s.himalayas_queries = _value(opt, "himalayas_queries", list, s.himalayas_queries, "sources.options")
    s.himalayas_max_pages = _value(opt, "himalayas_max_pages", int, s.himalayas_max_pages, "sources.options")
    s.jobicy_geos = _value(opt, "jobicy_geos", list, s.jobicy_geos, "sources.options")
    s.user_agent = _value(opt, "user_agent", str, s.user_agent, "sources.options")

    flt = _table(raw, "filters")
    s.title_must_contain = [w.lower() for w in _value(flt, "title_must_contain", list, [], "filters")]
    s.max_age_days = _value(flt, "max_age_days", int, s.max_age_days, "filters")

    sco = _table(raw, "scoring")
    s.remote_points = _value(sco, "remote_points", int, s.remote_points, "scoring")
    s.pay_points = _value(sco, "pay_points", int, s.pay_points, "scoring")
    s.title_points = _points(_table(sco, "title", "scoring.title"), "scoring.title")
    s.description_points = _points(_table(sco, "description", "scoring.description"), "scoring.description")

    out = _table(raw, "output")
    s.output_folder = _value(out, "folder", str, s.output_folder, "output")
    s.top = _value(out, "top", int, s.top, "output")

    watch = raw.get("watchlist", [])
    if not isinstance(watch, list):
        raise ConfigError("[[watchlist]] entries should each start with [[watchlist]]")
    for i, entry in enumerate(watch, 1):
        missing = [k for k in ("company", "provider", "slug") if not str(entry.get(k, "")).strip()]
        if missing:
            raise ConfigError(f"watchlist entry {i} is missing: {', '.join(missing)}")
        if entry["provider"] not in PROVIDERS:
            raise ConfigError(f"watchlist entry {i} ({entry['company']}): unknown provider \"{entry['provider']}\". "
                              f"Use one of: {', '.join(PROVIDERS)}")
        s.watchlist.append({"company": entry["company"].strip(), "provider": entry["provider"],
                            "slug": entry["slug"].strip()})
    return s


# lists/
TRACKING_PARAMS = ("utm_", "ref", "source", "src", "gh_src", "lever-source", "trk")


def clean_url(url: str) -> str:
    """Drop tracking parameters like utm_source, keep ones like ?id=123."""
    parts = urlsplit(str(url).strip())
    if not parts.query:
        return str(url).strip()
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith(TRACKING_PARAMS)]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def norm_url(url: str) -> str:
    """Comparable form of a job link: clean_url(), lower case, no trailing slash or #fragment."""
    parts = urlsplit(clean_url(url))
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), parts.query, "")).lower()


@dataclass
class Lists:
    companies: list[str] = field(default_factory=list)
    title_words: list[str] = field(default_factory=list)
    words: list[str] = field(default_factory=list)
    hidden: set[str] = field(default_factory=set)


def read_list(path: Path) -> list[str]:
    """Lines of a list file, without blank lines and # comments."""
    if not path.exists():
        return []
    lines = (line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def load_lists(settings: Settings) -> Lists:
    d = settings.lists_dir
    return Lists(
        companies=[x.lower() for x in read_list(d / LIST_FILES["companies"])],
        title_words=[x.lower() for x in read_list(d / LIST_FILES["title_words"])],
        words=[x.lower() for x in read_list(d / LIST_FILES["words"])],
        hidden={norm_url(u) for u in read_list(d / LIST_FILES["hidden"])},
    )


def add_to_list(settings: Settings, kind: str, values: list[str]) -> list[str]:
    """Append entries that are not in the list yet. Returns the ones added."""
    path = settings.lists_dir / LIST_FILES[kind]
    path.parent.mkdir(parents=True, exist_ok=True)
    key = norm_url if kind == "hidden" else (lambda v: v.lower())
    have = {key(v) for v in read_list(path)}
    added = []
    for v in values:
        v = v.strip()
        if v and key(v) not in have:
            have.add(key(v))
            added.append(v)
    if added:
        text = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        if text and not text.endswith("\n"):
            text += "\n"
        path.write_text(text + "\n".join(added) + "\n", encoding="utf-8")
    return added


def init(home: Path) -> list[str]:
    """Create config.toml and lists/ from the examples. Never overwrites a file."""
    home = Path(home)
    created = []
    config = home / "config.toml"
    if not config.exists():
        shutil.copyfile(EXAMPLE_CONFIG, config)
        created.append("config.toml")
    (home / "lists").mkdir(parents=True, exist_ok=True)
    for name in LIST_FILES.values():
        target = home / "lists" / name
        if not target.exists():
            shutil.copyfile(EXAMPLE_LISTS / name, target)
            created.append(f"lists/{name}")
    return created
