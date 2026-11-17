"""Generate the simulated bus offers used by BusBidder Spain.

Run from the repository root:

    python3 tools/generate_data.py

The script reads the companies and destinations from data/. For every
company and destination it fixes a route (transfers, normal price, normal
driving time), runs that route on four to six days of the travel week and
writes one offer per fare type for each departure. Prices, durations and
fare conditions follow each company's profile. The result goes to
data/offers.csv. A fixed seed makes the output identical on every run, so
the dataset can be reproduced from the script.
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 4420

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# The travel week that all offers fall inside.
FIRST_TRAVEL_DATE = datetime(2026, 7, 10)
TRAVEL_DAYS = 7

# Settings that turn each company's written profile into behaviour.
# price_per_km and speed_kmh are averages. The generator adds random variation.
# Changeability is one of: none, fee, free.
COMPANY_SETTINGS = {
    "SOL": {  # SolRuta: low-cost daytime services
        "base_fare": 3.0,
        "price_per_km": 0.050,
        "speed_kmh": 68,
        "transfer_chance": 0.5,
        "departure_hours": range(7, 18),
        "changeable": ["none", "none", "fee"],
        "refundable_chance": 0.0,
        "luggage_kg": 15,
        "rating": 3.5,
        "co2_g_per_km": None,  # SolRuta does not report emissions
    },
    "CAM": {  # Camino Express: fast direct connections
        "base_fare": 6.0,
        "price_per_km": 0.105,
        "speed_kmh": 90,
        "transfer_chance": 0.0,
        "departure_hours": range(6, 21),
        "changeable": ["fee", "free"],
        "refundable_chance": 0.4,
        "luggage_kg": 25,
        "rating": 4.4,
        "co2_g_per_km": 30,
    },
    "COS": {  # CostaLink: strong coverage of coastal destinations
        "base_fare": 4.0,
        "price_per_km": 0.060,  # coastal routes, inland routes cost more
        "inland_price_factor": 1.4,
        "speed_kmh": 80,
        "transfer_chance": 0.1,  # coastal routes, inland routes always have one
        "departure_hours": range(6, 20),
        "changeable": ["none", "fee", "fee"],
        "refundable_chance": 0.1,
        "luggage_kg": 20,
        "rating": 4.0,
        "co2_g_per_km": 28,
    },
    "VER": {  # VerdeBus: environment-focused, modern vehicles
        "base_fare": 5.0,
        "price_per_km": 0.080,
        "speed_kmh": 78,
        "transfer_chance": 0.3,
        "departure_hours": range(7, 20),
        "changeable": ["free"],
        "refundable_chance": 0.6,
        "luggage_kg": 20,
        "rating": 4.2,
        "co2_g_per_km": 12,
    },
    "NOC": {  # NocheVia: overnight and late-evening services
        "base_fare": 4.0,
        "price_per_km": 0.065,
        "speed_kmh": 72,
        "transfer_chance": 0.3,
        "departure_hours": [20, 21, 22, 23, 0, 1],
        "changeable": ["none", "fee"],
        "refundable_chance": 0.1,
        "luggage_kg": 20,
        "rating": 3.8,
        "co2_g_per_km": 25,
    },
}

TRANSFER_MINUTES = 35

# Each route runs on this many of the seven travel days.
MIN_RUNNING_DAYS = 4
MAX_RUNNING_DAYS = 6

# Companies that sell two fare types on the same departure. Each entry is
# (fare_type, price_factor, changeable, refundable). Companies not listed
# sell one "standard" fare whose conditions come from COMPANY_SETTINGS.
FARE_TYPES = {
    "SOL": [
        ("basic", 1.00, "none", "no"),
        ("plus", 1.20, "fee", "no"),
    ],
    "CAM": [
        ("standard", 1.00, "fee", "no"),
        ("flex", 1.25, "free", "yes"),
    ],
}

OFFER_COLUMNS = [
    "offer_id",
    "company_id",
    "fare_type",
    "destination_id",
    "departure_date",
    "departure_time",
    "arrival_date",
    "arrival_time",
    "price_eur",
    "transfers",
    "luggage_kg",
    "changeable",
    "refundable",
    "available_seats",
    "rating",
    "co2_kg",
]


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as file:
        return list(csv.DictReader(file))


def make_route(rng, company_id, destination):
    """Fix the things that stay the same for one company on one route.

    Transfers, the normal price and the normal driving time belong to the
    route, so the same company does not look completely different from one
    day to the next.
    """
    settings = COMPANY_SETTINGS[company_id]
    distance = int(destination["distance_km"])
    coastal = destination["coastal"] == "yes"

    # Transfers. CostaLink always needs one transfer to inland destinations.
    if company_id == "COS" and not coastal:
        transfers = 1
    else:
        transfers = 1 if rng.random() < settings["transfer_chance"] else 0

    # Price: a fixed base fare plus a price per kilometre, varied by up to 15%.
    price_per_km = settings["price_per_km"]
    if company_id == "COS" and not coastal:
        price_per_km *= settings["inland_price_factor"]
    price = (settings["base_fare"] + distance * price_per_km) * rng.uniform(0.85, 1.15)

    # Duration: driving time plus time lost per transfer, varied by up to 10%.
    driving_minutes = distance / settings["speed_kmh"] * 60
    minutes = (driving_minutes + transfers * TRANSFER_MINUTES) * rng.uniform(0.9, 1.1)

    rating = settings["rating"] + rng.uniform(-0.4, 0.4)

    if settings["co2_g_per_km"] is None:
        co2 = ""
    else:
        co2 = f"{distance * settings['co2_g_per_km'] / 1000:.1f}"

    return {
        "company_id": company_id,
        "destination_id": destination["destination_id"],
        "transfers": transfers,
        "price": price,
        "minutes": minutes,
        "rating": min(5.0, max(1.0, rating)),
        "co2": co2,
    }


def fares_for(rng, company_id):
    """Return the fare types sold on one departure."""
    if company_id in FARE_TYPES:
        return FARE_TYPES[company_id]
    settings = COMPANY_SETTINGS[company_id]
    changeable = rng.choice(settings["changeable"])
    refundable = "yes" if rng.random() < settings["refundable_chance"] else "no"
    return [("standard", 1.00, changeable, refundable)]


def make_departures(rng, route, first_number):
    """Create every offer for one route across the travel week."""
    settings = COMPANY_SETTINGS[route["company_id"]]
    running_days = rng.randint(MIN_RUNNING_DAYS, MAX_RUNNING_DAYS)
    days = sorted(rng.sample(range(TRAVEL_DAYS), running_days))

    offers = []
    for day in days:
        hour = rng.choice(list(settings["departure_hours"]))
        minute = rng.choice([0, 15, 30, 45])
        departure = FIRST_TRAVEL_DATE + timedelta(days=day, hours=hour, minutes=minute)

        # Small day-to-day changes in price and traffic.
        day_price = route["price"] * rng.uniform(0.92, 1.08)
        minutes = 5 * round(route["minutes"] * rng.uniform(0.95, 1.05) / 5)
        arrival = departure + timedelta(minutes=minutes)

        for fare_type, price_factor, changeable, refundable in fares_for(rng, route["company_id"]):
            number = first_number + len(offers)
            offers.append({
                "offer_id": f"OFR-{number:05d}",
                "company_id": route["company_id"],
                "fare_type": fare_type,
                "destination_id": route["destination_id"],
                "departure_date": departure.strftime("%Y-%m-%d"),
                "departure_time": departure.strftime("%H:%M"),
                "arrival_date": arrival.strftime("%Y-%m-%d"),
                "arrival_time": arrival.strftime("%H:%M"),
                "price_eur": f"{day_price * price_factor:.2f}",
                "transfers": route["transfers"],
                "luggage_kg": settings["luggage_kg"],
                "changeable": changeable,
                "refundable": refundable,
                "available_seats": rng.randint(0, 45),
                "rating": f"{route['rating']:.1f}",
                "co2_kg": route["co2"],
            })
    return offers


def generate(rng, companies, destinations):
    offers = []
    for company in companies:
        for destination in destinations:
            route = make_route(rng, company["company_id"], destination)
            offers.extend(make_departures(rng, route, len(offers) + 1))
    return offers


def write_offers(path, offers):
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=OFFER_COLUMNS)
        writer.writeheader()
        writer.writerows(offers)


def main():
    rng = random.Random(SEED)
    companies = read_csv(DATA_DIR / "companies.csv")
    destinations = read_csv(DATA_DIR / "destinations.csv")
    offers = generate(rng, companies, destinations)
    write_offers(DATA_DIR / "offers.csv", offers)
    print(f"Wrote {len(offers)} offers to {DATA_DIR / 'offers.csv'}")


if __name__ == "__main__":
    main()
