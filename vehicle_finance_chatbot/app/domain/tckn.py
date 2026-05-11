from __future__ import annotations

import re

TCKN_PATTERN = re.compile(r"^[1-9]\d{10}$")


def is_valid_tckn(tckn: str | None) -> bool:
    """Validate Turkish national ID via the official checksum algorithm.

    A 11-digit number where d1..d9 produce d10 and d11 via specific sums.
    """
    if not tckn or not isinstance(tckn, str):
        return False
    if not TCKN_PATTERN.match(tckn):
        return False
    digits = [int(c) for c in tckn]
    odd_sum = digits[0] + digits[2] + digits[4] + digits[6] + digits[8]
    even_sum = digits[1] + digits[3] + digits[5] + digits[7]
    d10 = (odd_sum * 7 - even_sum) % 10
    if d10 != digits[9]:
        return False
    d11 = (sum(digits[:10])) % 10
    return d11 == digits[10]


def mask_tckn(tckn: str | None) -> str | None:
    if not tckn:
        return None
    if len(tckn) != 11:
        return "***"
    return f"{tckn[:3]}******{tckn[-2:]}"
