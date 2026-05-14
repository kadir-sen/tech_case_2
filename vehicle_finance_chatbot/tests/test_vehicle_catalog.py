"""Vehicle catalog fuzzy resolve testleri."""
from app.domain.vehicle_catalog import (
    canonical_name,
    is_commercial_model,
    resolve_vehicle_model,
)


def test_exact_match_returns_high_confidence():
    res = resolve_vehicle_model("Toyota Corolla")
    assert res.is_confident is True
    assert res.confidence >= 85
    assert res.model is not None
    assert res.model.model_name == "Toyota Corolla"


def test_typo_resolves_to_canonical():
    res = resolve_vehicle_model("Tyota Korola")
    assert res.is_confident is True
    assert res.model is not None
    assert res.model.model_name == "Toyota Corolla"


def test_lowercase_no_diacritics_resolves():
    res = resolve_vehicle_model("fort transit")
    assert res.is_confident is True
    assert res.model is not None
    assert res.model.model_name == "Ford Transit"


def test_unknown_model_returns_no_confident_match():
    res = resolve_vehicle_model("Lada Niva")
    assert res.is_confident is False
    # Bilinmeyen model commercial sayılmaz (case sadece kataloğa kayıtlı
    # ticari modelleri reddetmeyi ister).
    assert is_commercial_model("Lada Niva") is False


def test_canonical_name_for_typo():
    assert canonical_name("Tyota Korola") == "Toyota Corolla"
    assert canonical_name("Lada Niva") is None


def test_commercial_typo_is_still_rejected():
    # "fort transit" → Ford Transit (commercial) — fuzzy match'in iş
    # kurallarına hizmet ettiğini gösterir.
    assert is_commercial_model("fort transit") is True


def test_empty_input_returns_no_match():
    res = resolve_vehicle_model(None)
    assert res.model is None
    assert res.is_confident is False
    res = resolve_vehicle_model("")
    assert res.model is None
    assert res.is_confident is False
