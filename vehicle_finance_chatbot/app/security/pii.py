from __future__ import annotations

import re
from typing import Any, Protocol

from app.domain.tckn import mask_tckn

_PHONE_RE = re.compile(r"(?:\+?90)?\s*[\(\s]?5\d{2}[\)\s]?\s*\d{3}\s*\d{2}\s*\d{2}")
_TCKN_RE = re.compile(r"(?<!\d)([1-9]\d{10})(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _mask_phone(match: re.Match[str]) -> str:
    raw = re.sub(r"\D", "", match.group(0))
    if len(raw) < 4:
        return "***"
    return raw[:3] + "*" * (len(raw) - 5) + raw[-2:]


def mask_text(value: str) -> str:
    if not isinstance(value, str):
        return value
    out = _TCKN_RE.sub(lambda m: mask_tckn(m.group(1)) or "***", value)
    out = _PHONE_RE.sub(_mask_phone, out)
    out = _EMAIL_RE.sub(lambda m: m.group(0)[0] + "***@" + m.group(0).split("@", 1)[1], out)
    return out


def mask_payload(payload: Any) -> Any:
    if isinstance(payload, str):
        return mask_text(payload)
    if isinstance(payload, dict):
        return {k: mask_payload(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [mask_payload(v) for v in payload]
    return payload


class SecretStore(Protocol):
    """Interface for an encryption/secret service.

    A production deployment would back this with HSM/KMS or a bank-internal
    vault. In MVP we only mask, but the interface is here so the call-sites
    do not need to change.
    """

    def encrypt(self, plaintext: str) -> str:
        ...

    def decrypt(self, ciphertext: str) -> str:
        ...


class MaskOnlySecretStore:
    """Default implementation: returns masked values; cannot decrypt."""

    def encrypt(self, plaintext: str) -> str:  # noqa: D401 - protocol shape
        return mask_text(plaintext)

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext


default_secret_store: SecretStore = MaskOnlySecretStore()
