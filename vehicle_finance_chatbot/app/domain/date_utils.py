from __future__ import annotations

import re
from datetime import date


def compute_vehicle_age(registration_date: date | None, today: date | None = None) -> int | None:
    """Banking convention: vehicle age is the number of full years since
    the registration (tescil) date. Returns None when input is missing.
    """
    if registration_date is None:
        return None
    today = today or date.today()
    years = today.year - registration_date.year
    if (today.month, today.day) < (registration_date.month, registration_date.day):
        years -= 1
    return max(years, 0)


_DATE_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"), "ymd"),
    (re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})"), "dmy"),
    (re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})"), "dmy"),
]


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    s = text.strip()
    for pattern, order in _DATE_PATTERNS:
        m = pattern.search(s)
        if not m:
            continue
        try:
            if order == "ymd":
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            continue
    return None


def parse_model_year(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"\b(19|20)\d{2}\b", text)
    if m:
        return int(m.group(0))
    return None
