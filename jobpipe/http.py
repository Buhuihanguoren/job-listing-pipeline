"""requests with a small disk cache and one retry."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

import requests


class Fetcher:
    def __init__(self, cache_dir: Path | None = None, cache_hours: float = 6,
                 user_agent: str = "job-listing-pipeline", timeout: float = 30):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_hours = cache_hours
        self.timeout = timeout
        self.retry_pause = 2.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent, "Accept-Language": "en"})

    def _cache_path(self, url: str, key: str | None, as_json: bool) -> Path | None:
        if self.cache_dir is None:
            return None
        if not key:
            slug = re.sub(r"[^A-Za-z0-9]+", "_", url.split("://", 1)[-1])[:60]
            key = f"{slug}_{hashlib.sha1(url.encode()).hexdigest()[:8]}"
        return self.cache_dir / f"{key}.{'json' if as_json else 'txt'}"

    def get(self, url: str, as_json: bool = True, key: str | None = None, max_age_hours: float | None = None):
        """GET with cache. Raises requests.HTTPError on 4xx/5xx."""
        max_age = self.cache_hours if max_age_hours is None else max_age_hours
        path = self._cache_path(url, key, as_json) if max_age > 0 else None
        if path is not None and path.exists() and time.time() - path.stat().st_mtime < max_age * 3600:
            text = path.read_text(encoding="utf-8")
            return json.loads(text) if as_json else text
        response = self._request(url)
        response.raise_for_status()
        data = response.json() if as_json else response.text
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False) if as_json else data, encoding="utf-8")
        return data

    def _request(self, url: str):
        """Retry once on a network error or 502/503/504."""
        for attempt in (1, 2):
            try:
                response = self.session.get(url, timeout=self.timeout)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 2:
                    raise
            else:
                if response.status_code not in (502, 503, 504) or attempt == 2:
                    return response
            time.sleep(self.retry_pause)

    def try_get(self, url: str, as_json: bool = True, key: str | None = None, max_age_hours: float | None = None):
        """Like get(), but returns None on any error. For optional lookups."""
        try:
            return self.get(url, as_json=as_json, key=key, max_age_hours=max_age_hours)
        except Exception:
            return None

    def page(self, url: str) -> tuple[int, str] | None:
        """(status code, HTML) of a web page, never cached. None if it can't be reached."""
        try:
            response = self.session.get(url, timeout=15)
            return response.status_code, response.text
        except Exception:
            return None
