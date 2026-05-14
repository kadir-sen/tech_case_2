from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz, process

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
    """Substring tabanlı eski yol — testlerde basit eşleşme için korunur.
    Yazım hatalarına dirençli arama için ``resolve_vehicle_model`` kullanın."""
    norm = normalize_vehicle_model(vehicle_model)
    if not norm:
        return None
    for model in _CATALOG:
        if model.normalized_model_name in norm or norm in model.normalized_model_name:
            return model
    return None


# rapidfuzz threshold — bu skorun altındaki eşleşmeler "düşük güven" sayılır;
# çağıran katman LLM disambiguation yapabilir veya kullanıcıya yeniden sorar.
# 80 eşiği "Tyota Korola" gibi makul yazım hatalarını yakalar; rastgele
# girdileri ("Lada Niva") düşük güven olarak işaretler.
_FUZZY_CONFIDENT_THRESHOLD = 80
_FUZZY_CANDIDATE_THRESHOLD = 60


@dataclass(frozen=True)
class VehicleResolution:
    model: VehicleModel | None
    confidence: float  # 0..100
    is_confident: bool
    raw_input: str


def _catalog_normalized_names() -> dict[str, VehicleModel]:
    return {m.normalized_model_name.replace("_", " "): m for m in _CATALOG}


def resolve_vehicle_model(vehicle_model: str | None) -> VehicleResolution:
    """Yazım hatalarına dirençli model çözümleme.

    1. Önce exact / substring eşleşmesi denenir.
    2. Bulunamazsa rapidfuzz ile en yakın katalog adayı seçilir.
    3. Güven skoru eşiğe göre ``is_confident`` True/False döner — düşükse
       caller LLM disambiguation veya yeniden sorma akışı uygulamalıdır.
    """
    if not vehicle_model:
        return VehicleResolution(model=None, confidence=0.0, is_confident=False, raw_input="")

    direct = lookup_vehicle_model(vehicle_model)
    if direct is not None:
        return VehicleResolution(
            model=direct,
            confidence=100.0,
            is_confident=True,
            raw_input=vehicle_model,
        )

    normalized = normalize_vehicle_model(vehicle_model).replace("_", " ")
    candidates = _catalog_normalized_names()
    match = process.extractOne(
        normalized,
        list(candidates.keys()),
        scorer=fuzz.WRatio,
    )
    if match is None:
        return VehicleResolution(model=None, confidence=0.0, is_confident=False, raw_input=vehicle_model)
    candidate_key, score, _ = match
    if score < _FUZZY_CANDIDATE_THRESHOLD:
        return VehicleResolution(model=None, confidence=float(score), is_confident=False, raw_input=vehicle_model)
    chosen = candidates[candidate_key]
    return VehicleResolution(
        model=chosen,
        confidence=float(score),
        is_confident=score >= _FUZZY_CONFIDENT_THRESHOLD,
        raw_input=vehicle_model,
    )


def is_commercial_model(vehicle_model: str | None) -> bool:
    """True only if catalog confirms COMMERCIAL (with fuzzy resolve).

    Bilinmeyen / düşük güvenli modeller False döner; sadece kataloğa
    kayıtlı ticari modeller reddedilir.
    """
    resolution = resolve_vehicle_model(vehicle_model)
    return (
        resolution.model is not None
        and resolution.is_confident
        and resolution.model.vehicle_class == VehicleClass.COMMERCIAL
    )


def canonical_name(vehicle_model: str | None) -> str | None:
    """Resolve confidence yüksekse canonical katalog adını döndürür."""
    resolution = resolve_vehicle_model(vehicle_model)
    if resolution.is_confident and resolution.model is not None:
        return resolution.model.model_name
    return None
