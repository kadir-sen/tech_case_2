from __future__ import annotations

import re

_MILLION_WORDS = ("milyon",)
_THOUSAND_WORDS = ("bin",)

_TR_DIGIT_GROUP = re.compile(r"\d{1,3}(?:[\.\s]\d{3})+(?:,\d+)?")
_PLAIN_NUMBER = re.compile(r"\d+(?:[\.,]\d+)?")


def _to_float(token: str) -> float:
    """Convert a TR-formatted numeric token to float.

    Accepts: 3.800.000 | 3.800.000,50 | 3,5 | 3.5 | 3800000
    """
    t = token.strip().replace(" ", "")
    if "," in t and "." in t:
        # Both separators present: dot=thousand, comma=decimal (TR convention).
        t = t.replace(".", "").replace(",", ".")
    elif "," in t:
        # Comma is decimal separator.
        t = t.replace(",", ".")
    elif t.count(".") > 1:
        # Multiple dots: treat as thousand separators.
        t = t.replace(".", "")
    elif "." in t:
        head, _, tail = t.partition(".")
        if len(tail) == 3 and tail.isdigit():
            # Likely thousand separator (e.g. "3.800").
            t = head + tail
    return float(t)


def parse_amount(text: str | None) -> float | None:
    """Parse Turkish money expressions into a float (TRY units).

    Supports:
        "3 milyon", "3.5 milyon", "3,5 milyon"
        "900 bin"
        "1 milyon 250 bin"
        "3800000", "3.800.000", "3.800.000 TL"
    Returns None if no numeric content is found.
    """
    if text is None:
        return None
    s = text.strip().lower()
    if not s:
        return None

    s = s.replace("tl", " ").replace("₺", " ").replace("try", " ")
    s = re.sub(r"\s+", " ", s).strip()

    total = 0.0
    matched = False

    # "<num> milyon <num> bin"
    m = re.search(r"(\d+(?:[\.,]\d+)?)\s*milyon(?:\s*(\d+(?:[\.,]\d+)?)\s*bin)?", s)
    if m:
        total += _to_float(m.group(1)) * 1_000_000
        if m.group(2):
            total += _to_float(m.group(2)) * 1_000
        matched = True
        s = s.replace(m.group(0), " ", 1)

    # "<num> bin"
    m = re.search(r"(\d+(?:[\.,]\d+)?)\s*bin", s)
    if m and not matched:
        total += _to_float(m.group(1)) * 1_000
        matched = True
        s = s.replace(m.group(0), " ", 1)
    elif m and matched:
        # Handled above only when combined with milyon; ignore here.
        pass

    if matched:
        return total

    # Grouped digits: "3.800.000" / "3 800 000"
    m = _TR_DIGIT_GROUP.search(s)
    if m:
        return _to_float(m.group(0))

    # Plain number fallback.
    m = _PLAIN_NUMBER.search(s)
    if m:
        return _to_float(m.group(0))

    return None
