"""
backend/scripts/generate_synthetic_suppliers.py
Generates 10,000 synthetic suppliers with realistic distributions.

Output: backend/data/suppliers_synthetic_10k.json

Distributions (Task 2.1 spec):
  Size:         70% small / 25% medium / 5% large
  Category:     metals/electronics/machinery/automotive_parts ~15% each
                packaging/textiles/chemicals/construction_materials ~7-8% each
                food_ingredients/logistics/software_services/pharmaceuticals ~3-5% each
  Country:      DE/CN/US ~12% each, EU + India ~5-7%, long tail ~1-3%
  Certs:        30% none, 50% 1-2, 15% 3-5, 5% 6+ (industry-aware)
  Capacity/LT:  Scale by size; ~15% null on each (incomplete data realism)
  Tricky:       50-100 anti-hallucination stress cases (5%+ per category)

Deterministic with random.seed(42). No LLM calls — pure templating.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import uuid
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

OUTPUT_PATH = (
    Path(__file__).parent.parent / "data" / "suppliers_synthetic_10k.json"
)

TOTAL = 10_000
SEED = 42

# ── Categories with target weights (sum ~100) ────────────────────────
CATEGORY_WEIGHTS = {
    "metals": 15,
    "electronics": 15,
    "machinery": 15,
    "automotive_parts": 15,
    "packaging": 8,
    "textiles": 7,
    "chemicals": 7,
    "construction_materials": 8,
    "food_ingredients": 4,
    "logistics": 3,
    "software_services": 3,
    "pharmaceuticals": 0,  # remainder pushed below
}
# normalise remainder to 100
_remain = 100 - sum(CATEGORY_WEIGHTS.values())
CATEGORY_WEIGHTS["pharmaceuticals"] = _remain  # ~0; bump to 4
CATEGORY_WEIGHTS["pharmaceuticals"] = 4
# Re-normalise: deficit absorbed by metals/electronics
_deficit = sum(CATEGORY_WEIGHTS.values()) - 100
if _deficit > 0:
    CATEGORY_WEIGHTS["metals"] -= _deficit

# ── Countries with weights and per-country city pool ────────────────
# (city_name, lat, lng). Multiple cities per country so suppliers spread out.
COUNTRY_CITIES: dict[str, list[tuple[str, float, float]]] = {
    "Germany": [
        ("Munich", 48.1351, 11.5820),
        ("Berlin", 52.5200, 13.4050),
        ("Hamburg", 53.5511, 9.9937),
        ("Frankfurt", 50.1109, 8.6821),
        ("Stuttgart", 48.7758, 9.1829),
        ("Cologne", 50.9375, 6.9603),
        ("Düsseldorf", 51.2277, 6.7735),
        ("Leipzig", 51.3397, 12.3731),
        ("Dortmund", 51.5136, 7.4653),
        ("Bremen", 53.0793, 8.8017),
        ("Hannover", 52.3759, 9.7320),
    ],
    "China": [
        ("Shanghai", 31.2304, 121.4737),
        ("Shenzhen", 22.5431, 114.0579),
        ("Beijing", 39.9042, 116.4074),
        ("Guangzhou", 23.1291, 113.2644),
        ("Suzhou", 31.2989, 120.5853),
        ("Hangzhou", 30.2741, 120.1551),
        ("Chengdu", 30.5728, 104.0668),
        ("Wuhan", 30.5928, 114.3055),
        ("Tianjin", 39.3434, 117.3616),
    ],
    "USA": [
        ("Chicago", 41.8781, -87.6298),
        ("Houston", 29.7604, -95.3698),
        ("Detroit", 42.3314, -83.0458),
        ("Los Angeles", 34.0522, -118.2437),
        ("Pittsburgh", 40.4406, -79.9959),
        ("Atlanta", 33.7490, -84.3880),
        ("Boston", 42.3601, -71.0589),
        ("Cleveland", 41.4993, -81.6944),
        ("Charlotte", 35.2271, -80.8431),
    ],
    "France": [
        ("Paris", 48.8566, 2.3522),
        ("Lyon", 45.7640, 4.8357),
        ("Marseille", 43.2965, 5.3698),
        ("Toulouse", 43.6047, 1.4442),
        ("Lille", 50.6292, 3.0573),
        ("Nantes", 47.2184, -1.5536),
    ],
    "United Kingdom": [
        ("Birmingham", 52.4862, -1.8904),
        ("Manchester", 53.4808, -2.2426),
        ("Leeds", 53.8008, -1.5491),
        ("Sheffield", 53.3811, -1.4701),
        ("Coventry", 52.4068, -1.5197),
        ("London", 51.5074, -0.1278),
    ],
    "Italy": [
        ("Milan", 45.4642, 9.1900),
        ("Turin", 45.0703, 7.6869),
        ("Bologna", 44.4949, 11.3426),
        ("Naples", 40.8518, 14.2681),
        ("Brescia", 45.5416, 10.2118),
    ],
    "Spain": [
        ("Barcelona", 41.3851, 2.1734),
        ("Madrid", 40.4168, -3.7038),
        ("Bilbao", 43.2630, -2.9350),
        ("Valencia", 39.4699, -0.3763),
        ("Zaragoza", 41.6488, -0.8891),
    ],
    "Poland": [
        ("Warsaw", 52.2297, 21.0122),
        ("Krakow", 50.0647, 19.9450),
        ("Wroclaw", 51.1079, 17.0385),
        ("Poznan", 52.4064, 16.9252),
        ("Gdansk", 54.3520, 18.6466),
    ],
    "Netherlands": [
        ("Amsterdam", 52.3676, 4.9041),
        ("Rotterdam", 51.9244, 4.4777),
        ("Eindhoven", 51.4416, 5.4697),
        ("Utrecht", 52.0907, 5.1214),
    ],
    "India": [
        ("Mumbai", 19.0760, 72.8777),
        ("Bangalore", 12.9716, 77.5946),
        ("Chennai", 13.0827, 80.2707),
        ("Pune", 18.5204, 73.8567),
        ("Hyderabad", 17.3850, 78.4867),
        ("Ahmedabad", 23.0225, 72.5714),
    ],
    "Japan": [
        ("Tokyo", 35.6762, 139.6503),
        ("Osaka", 34.6937, 135.5023),
        ("Nagoya", 35.1815, 136.9066),
        ("Yokohama", 35.4437, 139.6380),
    ],
    "South Korea": [
        ("Seoul", 37.5665, 126.9780),
        ("Busan", 35.1796, 129.0756),
        ("Incheon", 37.4563, 126.7052),
    ],
    "Mexico": [
        ("Monterrey", 25.6866, -100.3161),
        ("Guadalajara", 20.6597, -103.3496),
        ("Mexico City", 19.4326, -99.1332),
    ],
    "Brazil": [
        ("Sao Paulo", -23.5505, -46.6333),
        ("Rio de Janeiro", -22.9068, -43.1729),
        ("Curitiba", -25.4284, -49.2733),
    ],
    "Canada": [
        ("Toronto", 43.6532, -79.3832),
        ("Montreal", 45.5017, -73.5673),
        ("Vancouver", 49.2827, -123.1207),
    ],
    "Czech Republic": [
        ("Prague", 50.0755, 14.4378),
        ("Brno", 49.1951, 16.6068),
        ("Ostrava", 49.8209, 18.2625),
    ],
    "Austria": [
        ("Vienna", 48.2082, 16.3738),
        ("Graz", 47.0707, 15.4395),
        ("Linz", 48.3069, 14.2858),
    ],
    "Belgium": [("Antwerp", 51.2194, 4.4025), ("Brussels", 50.8503, 4.3517)],
    "Switzerland": [("Zurich", 47.3769, 8.5417), ("Geneva", 46.2044, 6.1432)],
    "Sweden": [("Stockholm", 59.3293, 18.0686), ("Gothenburg", 57.7089, 11.9746)],
    "Norway": [("Oslo", 59.9139, 10.7522), ("Bergen", 60.3913, 5.3221)],
    "Denmark": [("Copenhagen", 55.6761, 12.5683), ("Aarhus", 56.1629, 10.2039)],
    "Finland": [("Helsinki", 60.1699, 24.9384), ("Tampere", 61.4978, 23.7610)],
    "Portugal": [("Lisbon", 38.7223, -9.1393), ("Porto", 41.1579, -8.6291)],
    "Ireland": [("Dublin", 53.3498, -6.2603), ("Cork", 51.8985, -8.4756)],
    "Turkey": [("Istanbul", 41.0082, 28.9784), ("Ankara", 39.9334, 32.8597)],
    "Greece": [("Athens", 37.9838, 23.7275), ("Thessaloniki", 40.6401, 22.9444)],
    "Romania": [("Bucharest", 44.4268, 26.1025), ("Cluj-Napoca", 46.7712, 23.6236)],
    "Hungary": [("Budapest", 47.4979, 19.0402)],
    "Slovakia": [("Bratislava", 48.1486, 17.1077)],
    "Vietnam": [("Hanoi", 21.0285, 105.8542), ("Ho Chi Minh City", 10.7769, 106.7009)],
    "Thailand": [("Bangkok", 13.7563, 100.5018)],
    "Indonesia": [("Jakarta", -6.2088, 106.8456)],
    "Malaysia": [("Kuala Lumpur", 3.1390, 101.6869)],
    "Singapore": [("Singapore", 1.3521, 103.8198)],
    "Australia": [("Sydney", -33.8688, 151.2093), ("Melbourne", -37.8136, 144.9631)],
    "UAE": [("Dubai", 25.2048, 55.2708), ("Abu Dhabi", 24.4539, 54.3773)],
    "Saudi Arabia": [("Riyadh", 24.7136, 46.6753), ("Jeddah", 21.4858, 39.1925)],
    "South Africa": [("Johannesburg", -26.2041, 28.0473), ("Cape Town", -33.9249, 18.4241)],
    "Egypt": [("Cairo", 30.0444, 31.2357)],
    "Argentina": [("Buenos Aires", -34.6037, -58.3816)],
    "Chile": [("Santiago", -33.4489, -70.6693)],
}

COUNTRY_WEIGHTS = {
    "Germany": 12,
    "China": 12,
    "USA": 12,
    "France": 6,
    "United Kingdom": 6,
    "Italy": 6,
    "Spain": 5,
    "Poland": 5,
    "Netherlands": 5,
    "India": 6,
    "Japan": 4,
    "South Korea": 3,
    "Mexico": 2,
    "Brazil": 2,
    "Canada": 2,
    "Czech Republic": 2,
    "Austria": 2,
    "Belgium": 2,
    "Switzerland": 2,
    "Sweden": 1,
    "Norway": 1,
    "Denmark": 1,
    "Finland": 1,
    "Portugal": 1,
    "Ireland": 1,
    "Turkey": 1,
    "Greece": 1,
    "Romania": 1,
    "Hungary": 1,
    "Slovakia": 1,
    "Vietnam": 1,
    "Thailand": 1,
    "Indonesia": 1,
    "Malaysia": 1,
    "Singapore": 1,
    "Australia": 1,
    "UAE": 1,
    "Saudi Arabia": 1,
    "South Africa": 1,
    "Egypt": 1,
    "Argentina": 1,
    "Chile": 1,
}

# ── Legal suffixes per country ───────────────────────────────────────
LEGAL_SUFFIX = {
    "Germany": ["GmbH", "AG", "GmbH & Co. KG"],
    "France": ["SA", "SAS", "SARL"],
    "United Kingdom": ["Ltd", "PLC", "Group"],
    "Italy": ["S.p.A.", "S.r.l."],
    "Spain": ["S.A.", "S.L."],
    "Netherlands": ["B.V.", "N.V."],
    "Poland": ["Sp. z o.o.", "S.A."],
    "Czech Republic": ["s.r.o.", "a.s."],
    "Austria": ["GmbH", "AG"],
    "Belgium": ["NV", "BV"],
    "Switzerland": ["AG", "SA"],
    "Sweden": ["AB"],
    "Norway": ["AS"],
    "Denmark": ["A/S"],
    "Finland": ["Oy"],
    "Portugal": ["Lda", "S.A."],
    "Ireland": ["Ltd", "DAC"],
    "China": ["Co. Ltd", "Group Co. Ltd"],
    "Japan": ["K.K.", "Corp"],
    "South Korea": ["Co. Ltd", "Corp"],
    "USA": ["Inc.", "LLC", "Corp"],
    "Canada": ["Inc.", "Ltd"],
    "Mexico": ["S.A. de C.V."],
    "Brazil": ["Ltda", "S.A."],
    "India": ["Pvt Ltd", "Ltd"],
    "Singapore": ["Pte Ltd"],
    "Malaysia": ["Sdn Bhd"],
    "Australia": ["Pty Ltd"],
    "UAE": ["LLC"],
    "Saudi Arabia": ["LLC"],
    "South Africa": ["Pty Ltd"],
    "Turkey": ["A.Ş."],
    "Greece": ["S.A."],
    "Romania": ["SRL", "SA"],
    "Hungary": ["Kft.", "Zrt."],
    "Slovakia": ["s.r.o."],
    "Vietnam": ["Co. Ltd"],
    "Thailand": ["Co. Ltd"],
    "Indonesia": ["PT"],
    "Egypt": ["S.A.E."],
    "Argentina": ["S.A."],
    "Chile": ["S.A."],
}

# ── Category templates ──────────────────────────────────────────────
CATEGORY_TEMPLATES: dict[str, dict] = {
    "metals": {
        "noun": ["Metals", "Steel", "Alloys", "Foundry", "Forge"],
        "desc": (
            "manufactures precision metal components including steel, aluminium, "
            "and copper alloys. CNC machining facility serving automotive, "
            "aerospace and construction segments."
        ),
        "capacity_unit": "kg/month",
        "industry_certs": ["ISO 9001", "ISO 14001", "ISO 45001", "AS9100", "IATF 16949"],
    },
    "electronics": {
        "noun": ["Electronics", "Microsystems", "Circuits", "Semiconductors"],
        "desc": (
            "designs and assembles industrial electronics including PCBs, "
            "embedded controllers, and IoT modules. Lead-free SMT production "
            "with full RoHS compliance."
        ),
        "capacity_unit": "units/month",
        "industry_certs": ["ISO 9001", "ISO 27001", "RoHS", "CE", "ISO 14001"],
    },
    "machinery": {
        "noun": ["Machinery", "Engineering", "Industrial Systems", "Mechatronics"],
        "desc": (
            "supplies industrial machinery: hydraulic presses, conveyor systems, "
            "packaging lines, and custom automation. Engineering team delivers "
            "turnkey installations across Europe."
        ),
        "capacity_unit": "units/month",
        "industry_certs": ["ISO 9001", "ISO 14001", "CE", "ISO 45001"],
    },
    "automotive_parts": {
        "noun": ["Automotive", "Auto Components", "Driveline", "Powertrain"],
        "desc": (
            "Tier-1 automotive parts manufacturer producing engine components, "
            "transmission gears, and chassis fittings. Serves OEMs across "
            "Europe and North America."
        ),
        "capacity_unit": "units/month",
        "industry_certs": ["IATF 16949", "ISO 9001", "ISO 14001", "ISO 45001"],
    },
    "packaging": {
        "noun": ["Packaging", "Cartons", "Pack Solutions", "Container"],
        "desc": (
            "manufactures industrial packaging solutions: corrugated cardboard, "
            "rigid plastics, and flexible films. Sustainable materials with "
            "FSC-certified supply chain."
        ),
        "capacity_unit": "units/month",
        "industry_certs": ["ISO 9001", "FSC", "PEFC", "ISO 14001"],
    },
    "textiles": {
        "noun": ["Textiles", "Fabrics", "Weavers", "Apparel"],
        "desc": (
            "produces technical and apparel textiles, including cotton, polyester "
            "blends, and recycled fibres. Sustainable dyeing process and audited "
            "labour practices."
        ),
        "capacity_unit": "meters/month",
        "industry_certs": ["ISO 9001", "OEKO-TEX Standard 100", "GOTS", "ISO 14001"],
    },
    "chemicals": {
        "noun": ["Chemicals", "Specialty Chemicals", "ChemTech", "Polymers"],
        "desc": (
            "supplies specialty chemicals: solvents, adhesives, coatings and "
            "polymer compounds. REACH-registered portfolio with full SDS "
            "documentation."
        ),
        "capacity_unit": "kg/month",
        "industry_certs": ["ISO 9001", "REACH", "ISO 14001", "ISO 45001"],
    },
    "construction_materials": {
        "noun": ["Construction", "Building Materials", "Cement", "Concrete"],
        "desc": (
            "manufactures construction materials: cement, aggregates, prefab "
            "concrete and structural steel. Serves residential and commercial "
            "projects in domestic and adjacent markets."
        ),
        "capacity_unit": "tonnes/month",
        "industry_certs": ["ISO 9001", "CE", "ISO 14001", "ISO 45001"],
    },
    "food_ingredients": {
        "noun": ["Food", "Ingredients", "Nutrition", "Agro"],
        "desc": (
            "produces food ingredients: dairy proteins, starches, plant extracts "
            "and functional additives. HACCP-controlled facility with traceable "
            "supply chain."
        ),
        "capacity_unit": "tonnes/month",
        "industry_certs": ["HACCP", "ISO 22000", "BRC", "ISO 9001", "FDA", "KOSHER", "HALAL"],
    },
    "logistics": {
        "noun": ["Logistics", "Freight", "Transport", "Supply Chain"],
        "desc": (
            "provides multimodal logistics services: road, rail, sea and air "
            "freight, customs brokerage and warehousing. GDP-compliant pharma "
            "lanes available."
        ),
        "capacity_unit": "tonnes/month",
        "industry_certs": ["ISO 9001", "ISO 27001", "ISO 14001", "GDPR"],
    },
    "software_services": {
        "noun": ["Software", "Digital", "Tech", "Systems"],
        "desc": (
            "delivers enterprise software services: cloud migration, MES "
            "integration, AI/ML pilots and managed support. ISO 27001-certified "
            "with GDPR-aligned data handling."
        ),
        "capacity_unit": "units/month",  # treated as projects/month
        "industry_certs": ["ISO 27001", "ISO 9001", "GDPR"],
    },
    "pharmaceuticals": {
        "noun": ["Pharma", "Bio", "Pharmaceuticals", "Life Sciences"],
        "desc": (
            "manufactures pharmaceutical APIs and finished dosage forms. "
            "GMP-compliant facility with serialization and cold-chain support."
        ),
        "capacity_unit": "kg/month",
        "industry_certs": ["ISO 9001", "ISO 14001", "FDA", "HACCP", "ISO 45001"],
    },
}

ALL_CERTS = [
    "ISO 9001", "ISO 14001", "ISO 27001", "ISO 45001", "ISO 22000",
    "IATF 16949", "AS9100", "OEKO-TEX Standard 100", "GOTS", "FSC", "PEFC",
    "REACH", "RoHS", "CE", "GDPR", "HACCP", "BRC", "FDA", "KOSHER", "HALAL",
]
CERT_ISSUERS = ["TÜV Rheinland", "SGS", "Bureau Veritas", "DNV", "DEKRA", "Intertek"]

# ── Cert assignment helpers ─────────────────────────────────────────


def _pick_certs(rng: random.Random, category: str, target_count: int) -> list[str]:
    """Pick `target_count` plausible certs for `category`.

    Industry-specific certs preferred first; fallback to global pool.
    Respects the explicit "not equivalent" rule for textiles (GOTS XOR OEKO-TEX).
    """
    industry = CATEGORY_TEMPLATES[category]["industry_certs"]
    pool = list(industry)
    extras = [c for c in ALL_CERTS if c not in pool]
    rng.shuffle(pool)
    rng.shuffle(extras)
    ordered = pool + extras
    chosen: list[str] = []
    for c in ordered:
        if len(chosen) >= target_count:
            break
        # Enforce GOTS XOR OEKO-TEX for textiles realism.
        if (
            c == "GOTS"
            and "OEKO-TEX Standard 100" in chosen
        ) or (
            c == "OEKO-TEX Standard 100"
            and "GOTS" in chosen
        ):
            continue
        chosen.append(c)
    return chosen


def _cert_details(rng: random.Random, certs: list[str]) -> dict[str, dict]:
    today = date(2026, 5, 30)
    out: dict[str, dict] = {}
    for cert in certs:
        issuer = rng.choice(CERT_ISSUERS)
        valid_days = rng.randint(60, 1460)
        valid_until = today + timedelta(days=valid_days)
        out[cert] = {
            "issuing_body": issuer,
            "valid_until": valid_until.isoformat(),
        }
    return out


# ── Size / capacity / lead-time generation ──────────────────────────

def _size_bucket(rng: random.Random) -> str:
    r = rng.random()
    if r < 0.70:
        return "small"
    if r < 0.95:
        return "medium"
    return "large"


def _capacity_for_size(rng: random.Random, size: str) -> float:
    if size == "small":
        return float(rng.randint(100, 10_000))
    if size == "medium":
        return float(rng.randint(10_000, 200_000))
    return float(rng.randint(200_000, 2_000_000))


def _lead_time_for_size(rng: random.Random, size: str) -> int:
    if size == "small":
        return rng.randint(7, 45)
    if size == "medium":
        return rng.randint(14, 60)
    return rng.randint(21, 90)


def _employees_text(size: str, rng: random.Random) -> str:
    if size == "small":
        return f"{rng.randint(5, 100)} employees"
    if size == "medium":
        return f"{rng.randint(100, 1000)} employees"
    return f"{rng.randint(1000, 8000)} employees"


# ── Cert count buckets per supplier ─────────────────────────────────

def _cert_count(rng: random.Random) -> int:
    r = rng.random()
    if r < 0.30:
        return 0
    if r < 0.80:
        return rng.randint(1, 2)
    if r < 0.95:
        return rng.randint(3, 5)
    return rng.randint(6, 8)


# ── Tricky case injection ────────────────────────────────────────────

TRICKY_PROB = 0.012  # ~1.2% → 120 suppliers across the corpus


def _maybe_make_tricky(
    rng: random.Random,
    category: str,
    certs: list[str],
    description: str,
) -> tuple[list[str], str, str | None]:
    """With small probability, twist this supplier into an anti-hallucination case.

    Returns (mutated_certs, mutated_description, tricky_kind|None).
    """
    if rng.random() > TRICKY_PROB:
        return certs, description, None

    kind = rng.choice(
        [
            "gots_only",
            "oekotex_only",
            "as9100_no_iso9001",
            "pefc_competing_fsc",
            "claims_uncertified",
        ]
    )

    if kind == "gots_only":
        certs = [c for c in certs if c != "OEKO-TEX Standard 100"]
        if "GOTS" not in certs:
            certs.append("GOTS")
    elif kind == "oekotex_only":
        certs = [c for c in certs if c != "GOTS"]
        if "OEKO-TEX Standard 100" not in certs:
            certs.append("OEKO-TEX Standard 100")
    elif kind == "as9100_no_iso9001":
        certs = [c for c in certs if c != "ISO 9001"]
        if "AS9100" not in certs:
            certs.append("AS9100")
    elif kind == "pefc_competing_fsc":
        certs = [c for c in certs if c != "FSC"]
        if "PEFC" not in certs:
            certs.append("PEFC")
    elif kind == "claims_uncertified":
        # Description name-drops ISO 22000 even though it's not in certs.
        if "ISO 22000" in certs:
            certs.remove("ISO 22000")
        description = (
            description
            + " Marketing materials reference ISO 22000-aligned processes."
        )

    return certs, description, kind


# ── Name + description builders ─────────────────────────────────────


def _build_name(
    rng: random.Random, city: str, category: str, country: str
) -> str:
    noun = rng.choice(CATEGORY_TEMPLATES[category]["noun"])
    suffix = rng.choice(LEGAL_SUFFIX.get(country, ["Co."]))
    return f"{city} {noun} {suffix}".strip()


def _build_description(
    rng: random.Random,
    name: str,
    country: str,
    category: str,
    size: str,
    certs: list[str],
) -> str:
    base = CATEGORY_TEMPLATES[category]["desc"]
    cert_phrase = (
        f"Holds {', '.join(certs[:4])}{' and more' if len(certs) > 4 else ''}."
        if certs
        else "Operates without ISO-level third-party certification."
    )
    employees = _employees_text(size, rng)
    return (
        f"{name} is a {country}-based supplier that {base} "
        f"{cert_phrase} Operates with {employees}."
    )


def _build_address(rng: random.Random, city: str, country: str) -> str:
    street_no = rng.randint(1, 999)
    streets = [
        "Industriestraße",
        "Park Avenue",
        "Industrial Road",
        "Avenue de l'Industrie",
        "Via Industria",
        "Industry Way",
    ]
    return f"{street_no} {rng.choice(streets)}, {city}, {country}"


def _jitter_latlng(rng: random.Random, lat: float, lng: float) -> tuple[float, float]:
    return (
        round(lat + rng.uniform(-0.1, 0.1), 6),
        round(lng + rng.uniform(-0.1, 0.1), 6),
    )


def _email_for_name(name: str, idx: int) -> str:
    slug = "".join(ch.lower() for ch in name if ch.isalnum())[:24] or f"supplier{idx}"
    return f"procurement@{slug}-{idx:05d}.example.com"


def _website_for_name(name: str, idx: int) -> str:
    slug = "".join(ch.lower() for ch in name if ch.isalnum())[:24] or f"supplier{idx}"
    return f"https://www.{slug}-{idx:05d}.example.com"


# ── Weighted picker ─────────────────────────────────────────────────


def _weighted_pick(rng: random.Random, weights: dict[str, int]) -> str:
    keys = list(weights.keys())
    vals = list(weights.values())
    return rng.choices(keys, weights=vals, k=1)[0]


# ── Main generator ──────────────────────────────────────────────────


def generate(total: int = TOTAL, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    out: list[dict] = []
    tricky_counter: Counter[str] = Counter()

    for idx in range(total):
        category = _weighted_pick(rng, CATEGORY_WEIGHTS)
        country = _weighted_pick(rng, COUNTRY_WEIGHTS)
        city, lat, lng = rng.choice(COUNTRY_CITIES[country])
        lat, lng = _jitter_latlng(rng, lat, lng)

        size = _size_bucket(rng)
        cert_count = _cert_count(rng)
        certs = _pick_certs(rng, category, cert_count)

        name = _build_name(rng, city, category, country)
        description = _build_description(rng, name, country, category, size, certs)

        certs, description, tricky_kind = _maybe_make_tricky(
            rng, category, certs, description
        )
        if tricky_kind:
            tricky_counter[tricky_kind] += 1

        # Apply 15% null-rate to capacity and lead_time separately.
        capacity_value: float | None = (
            None if rng.random() < 0.15 else _capacity_for_size(rng, size)
        )
        lead_time: int | None = (
            None if rng.random() < 0.15 else _lead_time_for_size(rng, size)
        )

        supplier = {
            "id": str(uuid.UUID(int=rng.getrandbits(128))),
            "name": name,
            "description": description,
            "category": category,
            "country": country,
            "city": city,
            "address": _build_address(rng, city, country),
            "latitude": lat,
            "longitude": lng,
            "certifications": certs,
            "certification_details": _cert_details(rng, certs),
            "capacity_value": capacity_value,
            "capacity_unit": CATEGORY_TEMPLATES[category]["capacity_unit"],
            "lead_time_days": lead_time,
            "website": _website_for_name(name, idx),
            "contact_email": _email_for_name(name, idx),
            "is_active": True,
            "size_bucket": size,
            "tricky_kind": tricky_kind,
        }
        out.append(supplier)

    return out, tricky_counter


def summary(records: list[dict], tricky_counter: Counter) -> None:
    cat_counter = Counter(r["category"] for r in records)
    country_counter = Counter(r["country"] for r in records)
    size_counter = Counter(r["size_bucket"] for r in records)
    cert_count_counter = Counter(len(r["certifications"]) for r in records)
    null_cap = sum(1 for r in records if r["capacity_value"] is None)
    null_lead = sum(1 for r in records if r["lead_time_days"] is None)

    print("\n------ Distribution summary ------")
    print(f"Total: {len(records)}")
    print("\nCategory:")
    for cat, n in cat_counter.most_common():
        print(f"  {cat:<25} {n:>5}  ({n / len(records):.1%})")
    print("\nTop 15 countries:")
    for c, n in country_counter.most_common(15):
        print(f"  {c:<25} {n:>5}  ({n / len(records):.1%})")
    print(f"\nCountries total: {len(country_counter)}")
    print("\nSize bucket:")
    for s, n in size_counter.most_common():
        print(f"  {s:<25} {n:>5}  ({n / len(records):.1%})")
    print("\nCert count distribution:")
    for k in sorted(cert_count_counter):
        n = cert_count_counter[k]
        print(f"  {k} certs               {n:>5}  ({n / len(records):.1%})")
    print(f"\nNull capacity: {null_cap} ({null_cap / len(records):.1%})")
    print(f"Null lead time: {null_lead} ({null_lead / len(records):.1%})")
    print("\nTricky cases:")
    for k, n in tricky_counter.most_common():
        print(f"  {k:<25} {n:>5}")
    print(f"  TOTAL TRICKY            {sum(tricky_counter.values()):>5}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--total", type=int, default=TOTAL)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    logger.info(
        "Generating %d synthetic suppliers (seed=%d) → %s",
        args.total, args.seed, args.output,
    )
    records, tricky_counter = generate(args.total, args.seed)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    summary(records, tricky_counter)
    print(f"\nWrote: {args.output} ({args.output.stat().st_size / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
