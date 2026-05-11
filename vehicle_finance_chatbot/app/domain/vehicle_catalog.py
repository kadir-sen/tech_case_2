from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import VehicleClass


@dataclass(frozen=True)
class VehicleModel:
    model_name: str
    normalized_model_name: str
    brand: str
    model_code: str
    vehicle_class: VehicleClass


# Mock catalog. In production this comes from the bank's vehicle/kasko value
# service. The catalog is the source of truth for binek vs. ticari.
_CATALOG: tuple[VehicleModel, ...] = (
    VehicleModel("Fiat Egea", "fiat_egea", "Fiat", "FIAT-EGEA", VehicleClass.PASSENGER),
    VehicleModel("Renault Clio", "renault_clio", "Renault", "RNLT-CLIO", VehicleClass.PASSENGER),
    VehicleModel("Renault Megane", "renault_megane", "Renault", "RNLT-MEGANE", VehicleClass.PASSENGER),
    VehicleModel("Toyota Corolla", "toyota_corolla", "Toyota", "TYT-COROLLA", VehicleClass.PASSENGER),
    VehicleModel("Volkswagen Polo", "vw_polo", "Volkswagen", "VW-POLO", VehicleClass.PASSENGER),
    VehicleModel("Volkswagen Passat", "vw_passat", "Volkswagen", "VW-PASSAT", VehicleClass.PASSENGER),
    VehicleModel("BMW 3 Series", "bmw_3", "BMW", "BMW-3", VehicleClass.PASSENGER),
    VehicleModel("Mercedes C-Class", "mercedes_c", "Mercedes", "MB-C", VehicleClass.PASSENGER),
    VehicleModel("Tesla Model 3", "tesla_m3", "Tesla", "TSL-M3", VehicleClass.PASSENGER),
    VehicleModel("Togg T10X", "togg_t10x", "Togg", "TGG-T10X", VehicleClass.PASSENGER),
    # Commercial models
    VehicleModel("Ford Transit", "ford_transit", "Ford", "FRD-TRANSIT", VehicleClass.COMMERCIAL),
    VehicleModel("Ford Transit Custom", "ford_transit_custom", "Ford", "FRD-TRANSIT-CSTM", VehicleClass.COMMERCIAL),
    VehicleModel("Mercedes Sprinter", "mercedes_sprinter", "Mercedes", "MB-SPRINTER", VehicleClass.COMMERCIAL),
    VehicleModel("Fiat Doblo", "fiat_doblo", "Fiat", "FIAT-DOBLO", VehicleClass.COMMERCIAL),
    VehicleModel("Volkswagen Crafter", "vw_crafter", "Volkswagen", "VW-CRAFTER", VehicleClass.COMMERCIAL),
    VehicleModel("Renault Kangoo", "renault_kangoo", "Renault", "RNLT-KANGOO", VehicleClass.COMMERCIAL),
    VehicleModel("Iveco Daily", "iveco_daily", "Iveco", "IVCO-DAILY", VehicleClass.COMMERCIAL),
)

# Heuristic keywords that strongly suggest a commercial vehicle when the model
# is not found in the catalog. Used only to flag for clarification — never as
# a final rejection without catalog confirmation.
_COMMERCIAL_HINTS: tuple[str, ...] = (
    "transit",
    "sprinter",
    "doblo",
    "crafter",
    "kangoo",
    "kamyon",
    "kamyonet",
    "minibüs",
    "minibus",
    "panelvan",
    "panel van",
    "daily",
    "ducato",
    "boxer",
    "jumper",
)


def normalize_vehicle_model(vehicle_model: str | None) -> str:
    if not vehicle_model:
        return ""
    text = vehicle_model.strip().lower()
    text = text.replace("ı", "i").replace("ş", "s").replace("ç", "c")
    text = text.replace("ğ", "g").replace("ü", "u").replace("ö", "o")
    for ch in (",", ".", "/", "\\", "(", ")"):
        text = text.replace(ch, " ")
    parts = [p for p in text.split() if p]
    return "_".join(parts)


def lookup_vehicle_model(vehicle_model: str | None) -> VehicleModel | None:
    norm = normalize_vehicle_model(vehicle_model)
    if not norm:
        return None
    for model in _CATALOG:
        if model.normalized_model_name in norm or norm in model.normalized_model_name:
            return model
    return None


def is_commercial_model(vehicle_model: str | None) -> bool:
    """True only if catalog confirms COMMERCIAL. Unknown models return False
    here; the caller should branch on `is_unknown_model` for clarification.
    """
    model = lookup_vehicle_model(vehicle_model)
    return model is not None and model.vehicle_class == VehicleClass.COMMERCIAL


def is_unknown_model(vehicle_model: str | None) -> bool:
    return lookup_vehicle_model(vehicle_model) is None


def has_commercial_hint(vehicle_model: str | None) -> bool:
    if not vehicle_model:
        return False
    lower = vehicle_model.lower()
    return any(h in lower for h in _COMMERCIAL_HINTS)
