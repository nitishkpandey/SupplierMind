"""Unit tests for the ReAct Parser tool registry + the five default tools.

Tests verify the tool *contract* — name, args, return shape — not LLM output.
External dependencies (Nominatim, Groq) are injected as fakes so the suite
stays deterministic and offline.
"""

from __future__ import annotations

import pytest

from app.agents.tools import build_default_registry
from app.agents.tools.cert_taxonomy import canonicalize_certification_tool
from app.agents.tools.geocode import geocode_location_tool
from app.agents.tools.industry_context import infer_industry_context_tool
from app.agents.tools.past_query_stub import lookup_past_query_tool
from app.agents.tools.quantity_parser import parse_quantity_unit_tool
from app.agents.tools.registry import Tool, ToolRegistry


# ── Registry contract ────────────────────────────────────────────────


def test_registry_register_and_get():
    reg = ToolRegistry()
    tool = Tool(name="echo", description="echo", args_schema={}, fn=lambda x: x)
    reg.register(tool)
    assert "echo" in reg
    assert reg.get("echo") is tool


def test_registry_duplicate_register_raises():
    reg = ToolRegistry()
    reg.register(Tool(name="t", description="d", args_schema={}, fn=lambda: None))
    with pytest.raises(ValueError):
        reg.register(Tool(name="t", description="d", args_schema={}, fn=lambda: None))


def test_registry_get_unknown_raises():
    reg = ToolRegistry()
    with pytest.raises(KeyError):
        reg.get("missing")


def test_registry_list_for_prompt_includes_all_tools():
    reg = ToolRegistry()
    reg.register(Tool(name="a", description="alpha", args_schema={"k": 1}, fn=lambda: None))
    reg.register(Tool(name="b", description="beta", args_schema={"k": 2}, fn=lambda: None))
    rendered = reg.list_for_prompt()
    assert "- a: alpha" in rendered
    assert "- b: beta" in rendered
    assert '"k": 1' in rendered
    assert '"k": 2' in rendered


def test_build_default_registry_has_five_tools():
    reg = build_default_registry()
    assert sorted(reg.names()) == sorted([
        "geocode_location",
        "canonicalize_certification",
        "infer_industry_context",
        "parse_quantity_unit",
        "lookup_past_query",
    ])


# ── geocode_location ─────────────────────────────────────────────────


class _FakeGeocoder:
    def __init__(self, result):
        self._result = result
        self.calls: list[str] = []

    def geocode(self, name):
        self.calls.append(name)
        return self._result


def test_geocode_returns_lat_lng_country_for_known_location():
    fake = _FakeGeocoder((48.137, 11.575))
    tool = geocode_location_tool(_geocoder=fake)
    out = tool.fn(location_name="Munich, Germany")
    assert out == {"found": True, "lat": 48.137, "lng": 11.575, "city": "Munich", "country": "Germany"}
    assert fake.calls == ["Munich, Germany"]


def test_geocode_returns_not_found_for_unresolvable_name():
    tool = geocode_location_tool(_geocoder=_FakeGeocoder(None))
    out = tool.fn(location_name="Nowhereville XYZ")
    assert out["found"] is False
    assert "no geocode result" in out["reason"]


def test_geocode_handles_empty_input():
    tool = geocode_location_tool(_geocoder=_FakeGeocoder((0, 0)))
    out = tool.fn(location_name="")
    assert out == {"found": False, "reason": "empty location_name"}


# ── canonicalize_certification ───────────────────────────────────────


def test_canonicalize_resolves_iso9001_variants():
    tool = canonicalize_certification_tool()
    out = tool.fn(cert_name="ISO 9001:2015")
    assert out["resolved"] is True
    assert out["canonical"] == "ISO 9001"
    assert out["category"] == "quality_management"


def test_canonicalize_returns_supersession_relationships():
    tool = canonicalize_certification_tool()
    out = tool.fn(cert_name="AS9100D")
    assert out["resolved"] is True
    assert out["canonical"] == "AS9100"
    assert "ISO 9001" in out["supersedes"]


def test_canonicalize_returns_not_resolved_for_unknown_cert():
    tool = canonicalize_certification_tool()
    out = tool.fn(cert_name="ACME-Quality-2099")
    assert out["resolved"] is False
    assert out["input"] == "ACME-Quality-2099"


# ── infer_industry_context ───────────────────────────────────────────


class _FakeLLM:
    def __init__(self, json_response: str):
        self._json_response = json_response
        self.calls: list[list[dict]] = []

    def complete_json(self, messages, **kwargs):
        self.calls.append(messages)
        return self._json_response


def test_infer_industry_context_returns_parsed_fields():
    llm = _FakeLLM('{"industry":"aerospace","common_certs":["AS9100","NADCAP"],"typical_units":"units/year"}')
    tool = infer_industry_context_tool(_llm=llm)
    out = tool.fn(product_description="precision machined aerospace parts")
    assert out == {"industry": "aerospace", "common_certs": ["AS9100", "NADCAP"], "typical_units": "units/year"}
    assert llm.calls, "LLM not called"


def test_infer_industry_context_handles_bad_json():
    llm = _FakeLLM("not json at all")
    tool = infer_industry_context_tool(_llm=llm)
    out = tool.fn(product_description="thing")
    assert out["industry"] is None
    assert out["common_certs"] == []


def test_infer_industry_context_empty_input_short_circuits():
    llm = _FakeLLM("{}")
    tool = infer_industry_context_tool(_llm=llm)
    out = tool.fn(product_description="")
    assert out == {"industry": None, "common_certs": [], "typical_units": None}
    assert llm.calls == [], "LLM should not be called on empty input"


# ── parse_quantity_unit ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "text, value, normalized_unit",
    [
        ("10k units/month", 10000.0, "units/month"),
        ("2.5M tons/year", 2_500_000.0, "tons/year"),
        ("500 kg", 500.0, "kg"),
        ("1,200 units/year", 1200.0, "units/year"),
        ("42", 42.0, None),
    ],
)
def test_parse_quantity_unit_known_shapes(text, value, normalized_unit):
    tool = parse_quantity_unit_tool()
    out = tool.fn(text=text)
    assert out["parsed"] is True, out
    assert out["value"] == value
    assert out["normalized_unit"] == normalized_unit


def test_parse_quantity_unit_unparseable_returns_parsed_false():
    tool = parse_quantity_unit_tool()
    out = tool.fn(text="lots and lots")
    assert out["parsed"] is False


# ── lookup_past_query stub ───────────────────────────────────────────


def test_lookup_past_query_stub_returns_empty_list():
    tool = lookup_past_query_tool()
    assert tool.fn(query_text="ISO 9001 packaging in Germany", top_k=5) == []
