"""Generate the simulated bus offers used by BusBidder Spain.

Run from the repository root:

    python3 tools/generate_data.py

The script reads the companies and destinations from data/, creates offers
whose prices, durations, transfers and fare conditions follow each company's
profile, and writes them to data/offers.csv. A fixed seed makes the output
identical on every run, so the dataset can be reproduced from the script.
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

OFFER_COLUMNS = [
    "offer_id",
    "company_id",
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


def make_offer(rng, number, company_id, destination):
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
    minutes = 5 * round(minutes / 5)

    day = rng.randrange(TRAVEL_DAYS)
    hour = rng.choice(list(settings["departure_hours"]))
    departure = FIRST_TRAVEL_DATE + timedelta(days=day, hours=hour, minutes=rng.choice([0, 15, 30, 45]))
    arrival = departure + timedelta(minutes=minutes)

    rating = settings["rating"] + rng.uniform(-0.4, 0.4)
    rating = min(5.0, max(1.0, rating))

    if settings["co2_g_per_km"] is None:
        co2 = ""
    else:
        co2 = f"{distance * settings['co2_g_per_km'] / 1000:.1f}"

    return {
        "offer_id": f"OFR-{number:05d}",
        "company_id": company_id,
        "destination_id": destination["destination_id"],
        "departure_date": departure.strftime("%Y-%m-%d"),
        "departure_time": departure.strftime("%H:%M"),
        "arrival_date": arrival.strftime("%Y-%m-%d"),
        "arrival_time": arrival.strftime("%H:%M"),
        "price_eur": f"{price:.2f}",
        "transfers": transfers,
        "luggage_kg": settings["luggage_kg"],
        "changeable": rng.choice(settings["changeable"]),
        "refundable": "yes" if rng.random() < settings["refundable_chance"] else "no",
        "available_seats": rng.randint(0, 45),
        "rating": f"{rating:.1f}",
        "co2_kg": co2,
    }


def generate(rng, companies, destinations):
    offers = []
    for company in companies:
        for destination in destinations:
            number = len(offers) + 1
            offers.append(make_offer(rng, number, company["company_id"], destination))
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
