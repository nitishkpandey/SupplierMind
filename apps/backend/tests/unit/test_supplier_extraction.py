import json

from app.services import supplier_extraction as extraction_module
from app.services.supplier_extraction import SupplierExtractionService


class _StubLLM:
    def __init__(self, payload: dict):
        self.payload = payload

    def complete_json(self, *args, **kwargs) -> str:
        return json.dumps(self.payload)


def _service(payload: dict) -> SupplierExtractionService:
    service = SupplierExtractionService.__new__(SupplierExtractionService)
    service.llm = _StubLLM(payload)
    return service


def _payload(**overrides) -> dict:
    base = {
        "name": "Acme Metals GmbH",
        "description": "Manufactures precision metal parts for industrial buyers.",
        "primary_products": ["precision metal parts"],
        "industries_served": ["industrial"],
        "country": None,
        "city": None,
        "address": None,
        "certifications": [],
        "capacity_value": None,
        "capacity_unit": None,
        "lead_time_days": None,
        "website": "https://acme.example",
        "contact_email": None,
        "citations": {"name": "Acme Metals GmbH"},
        "confidence": 0.8,
    }
    base.update(overrides)
    return base


def test_stage2_normalises_literal_null_strings(monkeypatch):
    monkeypatch.setattr(
        extraction_module,
        "fetch_page_content",
        lambda url: "Acme Metals GmbH manufactures precision metal parts.",
    )
    service = _service(
        _payload(
            country="null",
            city=" NULL ",
            address="N/A",
            capacity_unit="none",
            website="",
            contact_email="unknown",
        )
    )

    result = service.stage2_extract("https://acme.example")

    assert result is not None
    assert result["country"] is None
    assert result["city"] is None
    assert result["address"] is None
    assert result["capacity_unit"] is None
    assert result["contact_email"] is None
    assert result["website"] == "https://acme.example"
    assert result["latitude"] is None
    assert result["longitude"] is None


def test_stage2_preserves_clean_location_text_for_geoapify(monkeypatch):
    monkeypatch.setattr(
        extraction_module,
        "fetch_page_content",
        lambda url: "Acme Metals GmbH manufactures precision metal parts in Germany.",
    )
    service = _service(
        _payload(country="Germany", city="null", address="null"),
    )

    result = service.stage2_extract("https://acme.example")

    assert result is not None
    assert result["country"] == "Germany"
    assert result["city"] is None
    assert result["latitude"] is None
    assert result["longitude"] is None
