"""Decide whether a remote job's region fits where you live."""

from __future__ import annotations

import re

NO_REGION = {"", "remote", "remote job", "fully remote", "nan", "none", "unknown", "n/a"}
_TZ = re.compile(r"\b(?:gmt|utc)\s*([+\-\u2212])\s*(\d{1,2})(?::?\d{2})?", re.I)


def _words_pattern(words: list[str]) -> re.Pattern | None:
    words = sorted({w.strip().lower() for w in words if w.strip()}, key=len, reverse=True)
    if not words:
        return None
    alternatives = [re.escape(w).replace(r"\ ", r"\s+") for w in words]
    return re.compile(r"\b(?:" + "|".join(alternatives) + r")\b", re.I)


class RegionRules:
    def __init__(self, accept: list[str], utc_min: float = -12, utc_max: float = 14,
                 onsite_places: list[str] | None = None, country: str = ""):
        self._accept = _words_pattern(accept)
        self._places = _words_pattern(onsite_places or [])
        self.utc_min, self.utc_max = utc_min, utc_max
        self.country = country

    @classmethod
    def from_settings(cls, s) -> "RegionRules":
        return cls(s.accept_regions, s.utc_offset_min, s.utc_offset_max, s.onsite_places, s.country)

    def region_ok(self, text) -> bool | None:
        """True = you may take the job, False = you may not, None = the listing names no region."""
        if text is None:
            return None
        t = str(text).strip()
        if t.lower() in NO_REGION:
            return None
        if self._accept and self._accept.search(t):
            return True
        for sign, hours in _TZ.findall(t):
            offset = -int(hours) if sign in ("-", "−") else int(hours)
            if self.utc_min <= offset <= self.utc_max:
                return True
        return False

    def timezones_ok(self, offsets) -> bool | None:
        """For boards that list allowed UTC offsets (Himalayas). None = no restriction."""
        if not offsets:
            return None
        try:
            return any(self.utc_min <= float(o) <= self.utc_max for o in offsets)
        except (TypeError, ValueError):
            return None

    def onsite_ok(self, location: str) -> bool:
        """An office job in one of your onsite_places."""
        return bool(self._places and self._places.search(str(location or "")))

    def label(self, region: str, eligible: bool | None, limit: int = 120) -> str:
        """Location text for a remote job, e.g. 'Remote - Europe'."""
        region = (region or "").strip()
        if len(region) > limit:
            n = region.count(",") + 1
            if self.country and re.search(rf"\b{re.escape(self.country)}\b", region, re.I):
                region = f"{n} countries incl. {self.country}"
            else:
                region = region[:limit].rsplit(",", 1)[0] + f" ... ({n} countries)"
        if eligible is None:
            return f"Remote - region unclear ({region})" if region else "Remote - region unclear"
        return f"Remote - {region}" if region else "Remote"
