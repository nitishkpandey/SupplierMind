"""
backend/data/generate_dataset.py

Generates the SupplierBench synthetic dataset:
- 100 supplier profiles (10 per category × 10 categories)
- 25 benchmark queries with ground truth answers

WHY SYNTHETIC DATA IS SCIENTIFICALLY VALID:
Following methodology of MS MARCO, BEIR, TREC benchmarks.
Synthetic benchmarks are standard when no labeled dataset exists.
Key requirement: reproducibility — random.seed(42) ensures same output every run.

RUN: python data/generate_dataset.py
"""

import json
import math
import random
import uuid
from pathlib import Path

random.seed(42)  # CRITICAL: fixed seed = reproducible dataset

CATEGORIES = [
    "metals", "electronics", "logistics", "textiles", "chemicals",
    "machinery", "packaging", "food_ingredients", "software_services",
    "construction_materials",
]

CERT_POOL = [
    "ISO 9001", "ISO 14001", "ISO 27001", "ISO 45001", "ISO 22000",
    "CE", "IATF 16949", "AS9100", "REACH", "RoHS",
]

# European cities with lat/lng coordinates
CITIES = [
    ("Germany", "Bremen", 53.0793, 8.8017),
    ("Germany", "Hamburg", 53.5511, 9.9937),
    ("Germany", "Munich", 48.1351, 11.5820),
    ("Germany", "Berlin", 52.5200, 13.4050),
    ("Germany", "Frankfurt", 50.1109, 8.6821),
    ("Germany", "Cologne", 50.9333, 6.9500),
    ("Germany", "Stuttgart", 48.7758, 9.1829),
    ("Germany", "Düsseldorf", 51.2217, 6.7762),
    ("Germany", "Dortmund", 51.5136, 7.4653),
    ("Germany", "Hannover", 52.3759, 9.7320),
    ("Netherlands", "Amsterdam", 52.3676, 4.9041),
    ("Netherlands", "Rotterdam", 51.9244, 4.4777),
    ("Poland", "Warsaw", 52.2297, 21.0122),
    ("Poland", "Krakow", 50.0647, 19.9450),
    ("Czech Republic", "Prague", 50.0755, 14.4378),
    ("Austria", "Vienna", 48.2082, 16.3738),
    ("France", "Paris", 48.8566, 2.3522),
    ("France", "Lyon", 45.7640, 4.8357),
    ("Belgium", "Brussels", 50.8503, 4.3517),
    ("Sweden", "Stockholm", 59.3293, 18.0686),
]

DESCRIPTIONS = {
    "metals": (
        "Specializes in precision metal components including steel, aluminum, and copper alloys. "
        "State-of-the-art CNC machining facility with 20 years of experience in automotive and aerospace."
    ),
    "electronics": (
        "Distributor and manufacturer of electronic components including PCBs, sensors, and microcontrollers. "
        "Serves automotive, industrial automation, and consumer electronics markets."
    ),
    "logistics": (
        "Full-service logistics provider offering road, rail, and multimodal freight solutions across Europe. "
        "Temperature-controlled and hazardous goods transport available."
    ),
    "textiles": (
        "Technical textile manufacturer producing industrial fabrics, filtration media, and protective materials. "
        "Custom weaving and finishing to specification with OEKO-TEX certified production."
    ),
    "chemicals": (
        "Producer of specialty chemicals, solvents, and reagents for industrial and laboratory applications. "
        "Full REACH compliance and SDS documentation provided for all products."
    ),
    "machinery": (
        "Manufacturer of industrial automation equipment, conveyor systems, and material handling machinery. "
        "CE marked and EU Machinery Directive compliant. Full installation and maintenance services."
    ),
    "packaging": (
        "Manufacturer of cardboard, corrugated, and sustainable packaging for industrial and consumer goods. "
        "Custom design services available with FSC certified paper sourcing."
    ),
    "food_ingredients": (
        "Supplier of food-grade ingredients including flavor enhancers, stabilizers, and preservatives. "
        "HACCP certified and fully compliant with EU food law regulations."
    ),
    "software_services": (
        "Provider of enterprise software development, ERP integration, and digital transformation services. "
        "ISO 27001 certified information security management with 99.9% SLA."
    ),
    "construction_materials": (
        "Producer of structural concrete elements, precast components, and thermal insulation materials. "
        "CE marked products compliant with EU Construction Products Regulation."
    ),
}

CAPACITY_CONFIG = {
    "metals":                 (500,   50000,  "kg/month"),
    "electronics":            (1000,  100000, "units/month"),
    "logistics":              (10,    1000,   "shipments/day"),
    "textiles":               (1000,  50000,  "meters/month"),
    "chemicals":              (100,   10000,  "liters/month"),
    "machinery":              (5,     100,    "units/month"),
    "packaging":              (10000, 500000, "units/month"),
    "food_ingredients":       (500,   20000,  "kg/month"),
    "software_services":      (1,     50,     "projects/month"),
    "construction_materials": (100,   5000,   "tons/month"),
}


def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate distance in km between two lat/lng points."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlng / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def generate_supplier(category: str) -> dict:
    """Generate one synthetic supplier profile."""
    country, city, base_lat, base_lng = random.choice(CITIES)

    # Add realistic scatter around city center (up to 30km)
    max_deg = 30 / 111.0
    lat = round(base_lat + random.uniform(-max_deg, max_deg), 6)
    lng = round(base_lng + random.uniform(-max_deg, max_deg), 6)

    # Certifications — most have ISO 9001, some don't (realistic)
    certs = ["ISO 9001"] if random.random() > 0.25 else []
    others = random.sample([c for c in CERT_POOL if c != "ISO 9001"], random.randint(1, 3))
    certs.extend(others)

    min_cap, max_cap, cap_unit = CAPACITY_CONFIG[category]

    issuing_bodies = ["TÜV Rheinland", "SGS", "Bureau Veritas", "DNV", "Lloyd's Register"]
    name_suffix = random.choice(["GmbH", "AG", "S.A.", "Ltd.", "B.V."])
    city_clean = city.replace("ü", "ue").replace("ö", "oe").replace("ä", "ae")

    return {
        "id": str(uuid.uuid4()),
        "name": f"{city_clean} {category.replace('_', ' ').title()} {name_suffix}",
        "description": DESCRIPTIONS[category],
        "category": category,
        "country": country,
        "city": city,
        "address": f"{random.randint(1, 200)} Industriestraße, {city}, {country}",
        "latitude": lat,
        "longitude": lng,
        "certifications": certs,
        "certification_details": {
            cert: {
                "issuing_body": random.choice(issuing_bodies),
                "valid_until": f"202{random.randint(6, 9)}-{random.randint(1,12):02d}-28",
            }
            for cert in certs
        },
        "capacity_value": float(random.randint(min_cap, max_cap)),
        "capacity_unit": cap_unit,
        "lead_time_days": random.randint(7, 90),
        "website": f"https://www.example-supplier-{str(uuid.uuid4())[:8]}.com",
        "contact_email": f"procurement@example-{str(uuid.uuid4())[:8]}.com",
        "is_active": True,
    }


def find_matching(suppliers: list[dict], category=None, country=None,
                  center=None, radius_km=None, certs=None,
                  min_cap=None, cap_unit=None, max_lead=None) -> list[str]:
    """Find supplier IDs matching all given constraints."""
    results = []
    for s in suppliers:
        if category and s["category"] != category:
            continue
        if country and s["country"] != country:
            continue
        if certs and not all(c in s["certifications"] for c in certs):
            continue
        if min_cap and cap_unit:
            if s["capacity_unit"] != cap_unit or s["capacity_value"] < min_cap:
                continue
        if max_lead and s["lead_time_days"] > max_lead:
            continue
        if center and radius_km:
            d = haversine(center[0], center[1], s["latitude"], s["longitude"])
            if d > radius_km:
                continue
        results.append(s["id"])
    return results[:8]


def generate_queries(suppliers: list[dict]) -> list[dict]:
    """Generate 25 benchmark queries with ground truth."""
    templates = [
        # Simple (1-2 constraints)
        {"q": "Find metal suppliers in Germany", "d": "simple",
         "c": dict(category="metals", country="Germany")},
        {"q": "ISO 9001 certified electronics suppliers", "d": "simple",
         "c": dict(category="electronics", certs=["ISO 9001"])},
        {"q": "Logistics providers in Netherlands", "d": "simple",
         "c": dict(category="logistics", country="Netherlands")},
        {"q": "Software service companies in Germany", "d": "simple",
         "c": dict(category="software_services", country="Germany")},
        {"q": "Textile suppliers with ISO 14001 certification", "d": "simple",
         "c": dict(category="textiles", certs=["ISO 14001"])},
        {"q": "Chemical suppliers in Europe with REACH certification", "d": "simple",
         "c": dict(category="chemicals", certs=["REACH"])},
        {"q": "Packaging suppliers in Germany", "d": "simple",
         "c": dict(category="packaging", country="Germany")},
        {"q": "Food ingredient suppliers certified ISO 22000", "d": "simple",
         "c": dict(category="food_ingredients", certs=["ISO 22000"])},
        # Medium (3-4 constraints)
        {"q": "ISO 9001 certified metal suppliers in Germany with capacity over 2000 kg per month",
         "d": "medium",
         "c": dict(category="metals", country="Germany", certs=["ISO 9001"], min_cap=2000, cap_unit="kg/month")},
        {"q": "Electronics supplier in Germany with ISO 9001 and RoHS, lead time under 30 days",
         "d": "medium",
         "c": dict(category="electronics", country="Germany", certs=["ISO 9001", "RoHS"], max_lead=30)},
        {"q": "Logistics providers in Germany capacity over 50 shipments per day",
         "d": "medium",
         "c": dict(category="logistics", country="Germany", min_cap=50, cap_unit="shipments/day")},
        {"q": "ISO 27001 certified software services company in Germany",
         "d": "medium",
         "c": dict(category="software_services", country="Germany", certs=["ISO 27001"])},
        {"q": "Chemical suppliers in Germany with REACH and ISO 14001, capacity over 500 liters",
         "d": "medium",
         "c": dict(category="chemicals", country="Germany", certs=["REACH", "ISO 14001"], min_cap=500, cap_unit="liters/month")},
        {"q": "Packaging manufacturer with 50000+ units per month capacity in Netherlands",
         "d": "medium",
         "c": dict(category="packaging", country="Netherlands", min_cap=50000, cap_unit="units/month")},
        {"q": "Machinery supplier in Germany, CE certified, delivery under 45 days",
         "d": "medium",
         "c": dict(category="machinery", country="Germany", certs=["CE"], max_lead=45)},
        {"q": "ISO 9001 and ISO 14001 certified textile supplier in Germany",
         "d": "medium",
         "c": dict(category="textiles", country="Germany", certs=["ISO 9001", "ISO 14001"])},
        {"q": "Food ingredient supplier with ISO 22000, capacity over 1000 kg per month",
         "d": "medium",
         "c": dict(category="food_ingredients", certs=["ISO 22000"], min_cap=1000, cap_unit="kg/month")},
        {"q": "Construction materials supplier in Germany, CE marking, 500+ tons monthly",
         "d": "medium",
         "c": dict(category="construction_materials", country="Germany", certs=["CE"], min_cap=500, cap_unit="tons/month")},
        # Hard (5-6 constraints, including radius)
        {"q": "ISO 9001 certified bronze supplier within 50km of Bremen, 3000+ kg/month, lead time under 21 days",
         "d": "hard",
         "c": dict(category="metals", center=(53.0793, 8.8017), radius_km=50,
                   certs=["ISO 9001"], min_cap=3000, cap_unit="kg/month", max_lead=21)},
        {"q": "Electronics supplier within 30km of Hamburg, ISO 9001 and RoHS, 5000+ units/month, under 14 days",
         "d": "hard",
         "c": dict(category="electronics", center=(53.5511, 9.9937), radius_km=30,
                   certs=["ISO 9001", "RoHS"], min_cap=5000, cap_unit="units/month", max_lead=14)},
        {"q": "ISO 27001 software services within 100km of Munich, under 30 days",
         "d": "hard",
         "c": dict(category="software_services", center=(48.1351, 11.5820), radius_km=100,
                   certs=["ISO 27001"], max_lead=30)},
        {"q": "Chemical supplier REACH and ISO 14001 within 75km of Frankfurt, 1000+ liters/month",
         "d": "hard",
         "c": dict(category="chemicals", center=(50.1109, 8.6821), radius_km=75,
                   certs=["REACH", "ISO 14001"], min_cap=1000, cap_unit="liters/month")},
        {"q": "Packaging within 40km of Berlin, ISO 9001, 100000+ units/month, under 10 days",
         "d": "hard",
         "c": dict(category="packaging", center=(52.5200, 13.4050), radius_km=40,
                   certs=["ISO 9001"], min_cap=100000, cap_unit="units/month", max_lead=10)},
        {"q": "Textile within 60km of Amsterdam, ISO 9001 and ISO 14001, 5000+ meters/month",
         "d": "hard",
         "c": dict(category="textiles", center=(52.3676, 4.9041), radius_km=60,
                   certs=["ISO 9001", "ISO 14001"], min_cap=5000, cap_unit="meters/month")},
        {"q": "Food ISO 22000 within 80km of Warsaw, 2000+ kg/month, under 14 days",
         "d": "hard",
         "c": dict(category="food_ingredients", center=(52.2297, 21.0122), radius_km=80,
                   certs=["ISO 22000"], min_cap=2000, cap_unit="kg/month", max_lead=14)},
    ]

    queries = []
    for i, t in enumerate(templates):
        c = t["c"]
        ground_truth = find_matching(
            suppliers,
            category=c.get("category"),
            country=c.get("country"),
            center=c.get("center"),
            radius_km=c.get("radius_km"),
            certs=c.get("certs"),
            min_cap=c.get("min_cap"),
            cap_unit=c.get("cap_unit"),
            max_lead=c.get("max_lead"),
        )
        queries.append({
            "id": str(uuid.uuid4()),
            "query_number": i + 1,
            "raw_query": t["q"],
            "difficulty": t["d"],
            "constraints": c,
            "ground_truth_supplier_ids": ground_truth[:5],
            "ground_truth_count": len(ground_truth[:5]),
        })

    return queries


def main() -> None:
    out = Path(__file__).parent
    suppliers_file = out / "suppliers_synthetic.json"
    queries_file = out / "queries_benchmark.json"

    print("🏭 Generating SupplierBench dataset...")
    suppliers = [generate_supplier(cat) for cat in CATEGORIES for _ in range(10)]
    print(f"   ✅ {len(suppliers)} suppliers generated")

    with open(suppliers_file, "w", encoding="utf-8") as f:
        json.dump(suppliers, f, indent=2, ensure_ascii=False)

    queries = generate_queries(suppliers)
    print(f"   ✅ {len(queries)} benchmark queries generated")
    for q in queries:
        icon = "✅" if q["ground_truth_count"] >= 3 else "⚠️ "
        print(f"      {icon} Q{q['query_number']:02d} [{q['difficulty']:6s}] "
              f"{q['ground_truth_count']} matches — {q['raw_query'][:55]}...")

    with open(queries_file, "w", encoding="utf-8") as f:
        json.dump(queries, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Saved to:")
    print(f"   {suppliers_file}")
    print(f"   {queries_file}")


if __name__ == "__main__":
    main()