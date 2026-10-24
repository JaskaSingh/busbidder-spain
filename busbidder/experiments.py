"""Reproducible experiments behind the report's results.

Each experiment is a function registered by name with @experiment("E1").
It receives an ExperimentData object (the loaded data and profiles) and an
output folder, writes a CSV table and a short text summary, and returns the
summary. The experiments command runs all of them, or the ones named, so
every table in the report can be regenerated with one command.

Experiments never read or write the real booking file. Rankings use the
original seat counts, and experiments that book use a temporary file.
Output files contain no timestamps, so running the command twice gives
identical files.
"""

import csv
from pathlib import Path

from .filtering import constraints_for, filter_offers
from .loading import load_offers
from .registry import Registry
from .scoring import STRATEGIES, rank_offers

EXPERIMENTS = Registry("experiment")
experiment = EXPERIMENTS.register

CRITERIA_ORDER = ["price", "duration", "departure_time", "flexibility"]


class ExperimentData:
    """Everything the experiments need, loaded once by the CLI."""

    def __init__(self, companies, destinations, offers, profiles, data_dir):
        self.companies = companies
        self.destinations = destinations
        self.offers = offers
        self.profiles = profiles
        self.data_dir = Path(data_dir)

    def rank(self, profile, strategy="anchored", offers=None):
        filtered = filter_offers(self.offers if offers is None else offers, constraints_for(profile))
        return filtered, rank_offers(filtered.accepted, profile, strategy)


def write_csv(path, header, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(rows)


def write_text(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_experiments(data, output_dir, names=None):
    """Run the named experiments (all if names is None) in name order."""
    output_dir = Path(output_dir)
    summaries = {}
    for name in names or EXPERIMENTS.names():
        summaries[name] = EXPERIMENTS.get(name)(data, output_dir)
    return summaries


@experiment("E1")
def profile_comparison(data, output_dir):
    """Same route and dates, every profile, both strategies, top three each."""
    header = ["strategy", "profile", "rank", "offer_id", "company", "fare_type", "departure",
              "price_eur", "duration_min", *CRITERIA_ORDER, "total"]
    rows, lines = [], ["E1 Profile comparison: Madrid to Malaga, 12 to 14 July", ""]
    for strategy in STRATEGIES.names():
        winners = []
        lines.append(f"Strategy: {strategy}")
        for profile in data.profiles.values():
            filtered, ranking = data.rank(profile, strategy)
            for scored in ranking[:3]:
                offer = scored.offer
                rows.append([
                    strategy, profile.name, scored.rank, offer.offer_id, offer.company.name,
                    offer.fare.fare_type, offer.departure.strftime("%Y-%m-%d %H:%M"),
                    f"{offer.price_eur:.2f}", offer.duration_minutes,
                    *(f"{scored.scores[c]:.1f}" for c in CRITERIA_ORDER), f"{scored.total:.1f}",
                ])
            if ranking:
                top = ranking[0]
                winners.append(top.offer.offer_id)
                lines.append(
                    f"  {profile.name:<9} {len(filtered.accepted):>2} of {filtered.in_scope} offers kept. "
                    f"First: {top.offer.offer_id} {top.offer.company.name} {top.offer.fare.fare_type} "
                    f"{top.offer.departure:%d %b %H:%M} EUR {top.offer.price_eur:.2f} ({top.total:.1f})"
                )
            else:
                lines.append(f"  {profile.name:<9} no offers left")
        lines.append(f"  {len(set(winners))} different first-ranked offers for {len(winners)} profiles")
        lines.append("")
    write_csv(output_dir / "e1_profile_comparison.csv", header, rows)
    write_text(output_dir / "e1_profile_comparison.txt", lines)
    return lines


@experiment("E5")
def validation_counts(data, output_dir):
    """How the validation policy sorts the generated file and the invalid file."""
    header = ["file", "outcome", "field", "count"]
    rows, lines = [], ["E5 Validation outcomes by file and field", ""]
    for name in ("offers.csv", "offers_invalid.csv"):
        result = load_offers(data.data_dir / name, data.companies, data.destinations)
        rows.append([name, "accepted", "", len(result.offers)])
        lines.append(f"{name}: {result.summary()}")
        for outcome, items in (("rejected", result.rejected), ("review", result.review),
                               ("corrected", result.corrections)):
            counts = {}
            for item in items:
                counts[item.field] = counts.get(item.field, 0) + 1
            for field_name in sorted(counts):
                rows.append([name, outcome, field_name, counts[field_name]])
                lines.append(f"  {outcome:<9} {field_name:<16} {counts[field_name]}")
        lines.append("")
    write_csv(output_dir / "e5_validation_counts.csv", header, rows)
    write_text(output_dir / "e5_validation_counts.txt", lines)
    return lines
