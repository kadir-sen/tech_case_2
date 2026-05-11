from app.domain.tckn import is_valid_tckn, mask_tckn
from tests.conftest import VALID_TCKN_GUARANTOR, VALID_TCKN_OTHER


def test_is_valid_tckn_accepts_correct_numbers():
    assert is_valid_tckn(VALID_TCKN_GUARANTOR)
    assert is_valid_tckn(VALID_TCKN_OTHER)


def test_is_valid_tckn_rejects_garbage():
    assert not is_valid_tckn(None)
    assert not is_valid_tckn("")
    assert not is_valid_tckn("12345")
    assert not is_valid_tckn("01234567890")  # leading zero
    assert not is_valid_tckn("12345678901")  # checksum fail
    assert not is_valid_tckn("abcdefghijk")


def test_mask_tckn_format():
    masked = mask_tckn(VALID_TCKN_GUARANTOR)
    assert masked is not None
    assert masked.startswith(VALID_TCKN_GUARANTOR[:3])
    assert masked.endswith(VALID_TCKN_GUARANTOR[-2:])
    assert "*" in masked
