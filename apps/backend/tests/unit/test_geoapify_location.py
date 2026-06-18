from app.services.location_enrichment import GeoapifyLocationService


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Client:
    def __init__(self, responses: list[dict]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, params: dict, timeout: float):
        self.calls.append((url, params))
        return _Response(self.responses.pop(0))


def _feature(**props):
    return {
        "type": "Feature",
        "properties": {
            "city": props.get("city"),
            "country": props.get("country", "Germany"),
            "country_code": props.get("country_code", "de"),
            "formatted": props.get("formatted", "Düsseldorf, Germany"),
            "name": props.get("name", "Hogge Precision GmbH"),
            "rank": {"confidence": props.get("confidence", 0.95)},
        },
        "geometry": {"coordinates": [props.get("lon", 6.7735), props.get("lat", 51.2277)]},
    }


def test_geoapify_geocoding_validates_extracted_location():
    client = _Client([
        {"features": [_feature(city="Düsseldorf", confidence=0.98)]},
    ])
    service = GeoapifyLocationService(
        geocoding_api_key="geo-key",
        places_api_key="places-key",
        client=client,
    )

    location = service.enrich(
        {
            "name": "Hogge Precision",
            "address": "Düsseldorf, Germany",
            "city": None,
            "country": None,
        },
        constraints={"location_country": "Germany"},
    )

    assert location is not None
    assert location.city == "Düsseldorf"
    assert location.country == "Germany"
    assert location.latitude == 51.2277
    assert location.longitude == 6.7735
    assert location.source == "geoapify_geocoding"
    assert client.calls[0][1]["text"] == "Düsseldorf, Germany"


def test_geoapify_places_fallback_uses_company_name_and_query_context():
    client = _Client([
        {"features": [_feature(city="Munich", lat=48.137, lon=11.575, confidence=0.9)]},
    ])
    service = GeoapifyLocationService(
        geocoding_api_key="",
        places_api_key="places-key",
        client=client,
    )

    location = service.enrich(
        {"name": "Hogge Precision", "address": None, "city": None, "country": None},
        constraints={"location_city": "Bavaria", "location_country": "Germany"},
    )

    assert location is not None
    assert location.city == "Munich"
    assert location.country == "Germany"
    assert location.source == "geoapify_places"
    assert len(client.calls) == 1
    assert client.calls[0][1]["name"] == "Hogge Precision"
    assert client.calls[0][1]["categories"] == "commercial"
    assert client.calls[0][1]["filter"] == "rect:8.976,47.270,13.839,50.565"


def test_geoapify_geocoding_uses_company_name_when_page_location_missing():
    client = _Client([
        {
            "features": [
                _feature(
                    city="Munich",
                    lat=48.137,
                    lon=11.575,
                    name="Siemens",
                    formatted="Siemens, Otto-Hahn-Ring, 81739 Munich, Germany",
                    confidence=1.0,
                )
            ]
        },
    ])
    service = GeoapifyLocationService(
        geocoding_api_key="geo-key",
        places_api_key="places-key",
        client=client,
    )

    location = service.enrich(
        {"name": "Siemens", "address": None, "city": None, "country": None},
        constraints={"location_city": "Munich", "location_country": "Germany"},
    )

    assert location is not None
    assert location.city == "Munich"
    assert location.country == "Germany"
    assert location.source == "geoapify_geocoding"
    assert len(client.calls) == 1
    assert client.calls[0][1]["text"] == "Siemens, Munich, Germany"


def test_geoapify_geocoding_rejects_unmatched_company_name_for_context():
    client = _Client([
        {
            "features": [
                _feature(
                    city="Munich",
                    name="Different Manufacturing GmbH",
                    confidence=1.0,
                )
            ]
        },
    ])
    service = GeoapifyLocationService(
        geocoding_api_key="geo-key",
        places_api_key="",
        client=client,
    )

    location = service.enrich(
        {"name": "Hogge Precision", "address": None, "city": None, "country": None},
        constraints={"location_city": "Munich", "location_country": "Germany"},
    )

    assert location is None


def test_geoapify_places_requires_bounded_query_context():
    client = _Client([
        {"features": [_feature(city="Munich", confidence=0.9)]},
    ])
    service = GeoapifyLocationService(
        geocoding_api_key="",
        places_api_key="places-key",
        client=client,
    )

    location = service.enrich(
        {"name": "Hogge Precision", "address": None, "city": None, "country": None},
        constraints={},
    )

    assert location is None
    assert client.calls == []


def test_geoapify_places_rejects_unmatched_company_name():
    client = _Client([
        {"features": [_feature(city="Munich", name="Different Manufacturing GmbH", confidence=0.9)]},
    ])
    service = GeoapifyLocationService(
        geocoding_api_key="",
        places_api_key="places-key",
        client=client,
    )

    location = service.enrich(
        {"name": "Hogge Precision", "address": None, "city": None, "country": None},
        constraints={"location_city": "Bavaria", "location_country": "Germany"},
    )

    assert location is None


def test_geoapify_rejects_low_confidence_location():
    client = _Client([
        {"features": [_feature(city="Düsseldorf", confidence=0.2)]},
        {"features": []},
    ])
    service = GeoapifyLocationService(
        geocoding_api_key="geo-key",
        places_api_key="places-key",
        client=client,
    )

    location = service.enrich(
        {"name": "Hogge Precision", "address": "Düsseldorf, Germany"},
        constraints={},
    )

    assert location is None
