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

import copy
import csv
import random
import tempfile
from datetime import datetime
from pathlib import Path

from .booking import BookingStore
from .errors import BookingError
from .filtering import constraints_for, filter_offers
from .loading import load_offers
from .profiles import validate_weights
from .registry import Registry
from .reporting import short_name
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


def with_price_weight(weights, price_weight):
    """New weights with the given price weight, keeping the others in proportion.

    The other weights are scaled to share what is left of 100 and rounded to
    whole percentages. Any rounding difference goes to the largest of them,
    so the total is always exactly 100.
    """
    others = {name: weight for name, weight in weights.items() if name != "price"}
    remaining = 100 - price_weight
    total_others = sum(others.values())
    if total_others == 0:
        share = remaining // len(others)
        scaled = {name: share for name in others}
    else:
        scaled = {name: round(remaining * weight / total_others) for name, weight in others.items()}
    largest = max(others, key=lambda name: (others[name], name))
    scaled[largest] += remaining - sum(scaled.values())
    return {"price": price_weight, **scaled}


def profile_variant(profile, **changes):
    """A copy of a profile with some settings changed. The original is untouched."""
    variant = copy.copy(profile)
    for name, value in changes.items():
        setattr(variant, name, value)
    return variant


@experiment("E2")
def weight_sensitivity(data, output_dir):
    """Price weight from 0 to 100% in steps of 10, other weights in proportion."""
    header = ["profile", "price_weight", "weights", "winner", "company", "fare_type",
              "price_eur", "total", "lead_over_second"]
    rows, lines = [], ["E2 Weight sensitivity: price weight 0 to 100%, anchored scores", ""]
    for profile in data.profiles.values():
        segments = []
        for price_weight in range(0, 101, 10):
            weights = validate_weights(with_price_weight(profile.weights, price_weight))
            variant = profile_variant(profile, weights=weights)
            _, ranking = data.rank(variant)
            if not ranking:
                continue
            top = ranking[0]
            lead = top.total - ranking[1].total if len(ranking) > 1 else None
            rows.append([
                profile.name, price_weight,
                " ".join(f"{name}={weight}" for name, weight in weights.items()),
                top.offer.offer_id, top.offer.company.name, top.offer.fare.fare_type,
                f"{top.offer.price_eur:.2f}", f"{top.total:.1f}",
                "" if lead is None else f"{lead:.1f}",
            ])
            label = f"{top.offer.offer_id} {top.offer.company.name} {top.offer.fare.fare_type}"
            if segments and segments[-1][2] == label:
                segments[-1][1] = price_weight
            else:
                segments.append([price_weight, price_weight, label])
        current = profile.weights["price"]
        lines.append(f"{profile.name} (own price weight {current}%):")
        for start, end, label in segments:
            mark = "  <- own weight" if start <= current <= end else ""
            lines.append(f"  price {start:>3}% to {end:>3}%: {label}{mark}")
        lines.append(f"  {len(segments)} different winner(s) across the range")
        lines.append("")
    write_csv(output_dir / "e2_weight_sensitivity.csv", header, rows)
    write_text(output_dir / "e2_weight_sensitivity.txt", lines)
    return lines


@experiment("E4")
def budget_cliff(data, output_dir):
    """How the budget, a hard constraint, changes what is kept and what wins.

    Two parts for the budget profile: budgets one cent either side of the
    most expensive offer it keeps (the cliff edge), and a sweep from EUR 30
    to EUR 80.
    """
    profile = data.profiles["budget"]
    _, ranking = data.rank(profile)
    edge = max(scored.offer.price_eur for scored in ranking)
    edge_offer = max(ranking, key=lambda scored: scored.offer.price_eur).offer
    budgets = [round(edge - 0.01, 2), edge, round(edge + 0.01, 2)]
    sweep = list(range(30, 81, 5))

    header = ["part", "budget_eur", "offers_kept", "edge_offer_kept", "winner", "company",
              "winner_price_eur", "winner_price_score", "total"]
    rows = []
    lines = [
        "E4 Budget cliff for the budget profile (anchored scores)",
        f"Most expensive offer kept at EUR 50: {edge_offer.offer_id} {edge_offer.company.name} "
        f"EUR {edge_offer.price_eur:.2f}",
        "",
    ]
    for part, values in (("edge", budgets), ("sweep", sweep)):
        lines.append("Cliff edge:" if part == "edge" else "Budget sweep:")
        for budget in values:
            variant = profile_variant(profile, max_price_eur=budget)
            filtered, ranking = data.rank(variant)
            kept_ids = {offer.offer_id for offer in filtered.accepted}
            edge_kept = edge_offer.offer_id in kept_ids
            if ranking:
                top = ranking[0]
                rows.append([part, f"{budget:.2f}", len(filtered.accepted), edge_kept,
                             top.offer.offer_id, top.offer.company.name,
                             f"{top.offer.price_eur:.2f}", f"{top.scores['price']:.1f}",
                             f"{top.total:.1f}"])
                lines.append(
                    f"  EUR {budget:>6.2f}: {len(filtered.accepted):>2} kept, "
                    f"{edge_offer.offer_id} {'kept' if edge_kept else 'removed'}. "
                    f"First: {top.offer.offer_id} {top.offer.company.name} "
                    f"(price score {top.scores['price']:.0f}, total {top.total:.1f})"
                )
            else:
                rows.append([part, f"{budget:.2f}", 0, False, "", "", "", "", ""])
                lines.append(f"  EUR {budget:>6.2f}:  0 kept")
        lines.append("")
    write_csv(output_dir / "e4_budget_cliff.csv", header, rows)
    write_text(output_dir / "e4_budget_cliff.txt", lines)
    return lines


@experiment("E3")
def rank_reversal(data, output_dir):
    """Does removing one offer change the order of the others?

    For every profile and strategy, each accepted offer is left out in turn
    and the remaining offers are ranked again. If their order differs from
    their order in the full ranking, the left-out offer influenced how the
    others compare with each other. Read the other way round, adding that
    offer reversed their order.
    """
    header = ["strategy", "profile", "offers", "left_out", "left_out_rank",
              "order_changed", "winner_with", "winner_without"]
    rows = []
    lines = ["E3 Rank reversal: leave each accepted offer out and rank the rest again", ""]
    examples = []
    for strategy in STRATEGIES.names():
        lines.append(f"Strategy: {strategy}")
        for profile in data.profiles.values():
            filtered, full = data.rank(profile, strategy)
            full_order = [scored.offer.offer_id for scored in full]
            changed = winner_changed = 0
            for scored in full:
                left_out = scored.offer
                rest = [offer for offer in filtered.accepted if offer is not left_out]
                _, reranked = data.rank(profile, strategy, offers=rest)
                new_order = [s.offer.offer_id for s in reranked]
                expected = [offer_id for offer_id in full_order if offer_id != left_out.offer_id]
                order_changed = new_order != expected
                changed += order_changed
                if order_changed and new_order and new_order[0] != expected[0]:
                    winner_changed += 1
                    examples.append((strategy, profile, left_out, scored.rank, full, reranked))
                rows.append([
                    strategy, profile.name, len(full), left_out.offer_id, scored.rank,
                    order_changed, expected[0] if expected else "", new_order[0] if new_order else "",
                ])
            lines.append(
                f"  {profile.name:<9} {len(full):>2} offers: {changed} of {len(full)} removals "
                f"change the order of the rest, {winner_changed} change the winner"
            )
        lines.append("")

    for strategy, profile, left_out, rank, full, reranked in examples:
        lines.append(
            f"Example ({strategy}, {profile.name}): leaving out {left_out.offer_id} "
            f"{left_out.company.name}, ranked {rank} of {len(full)}, swaps the top two."
        )
        others = {s.offer.offer_id: s for s in reranked}
        for scored in full[:2]:
            offer_id = scored.offer.offer_id
            after = others[offer_id]
            def detail(item):
                return " ".join(f"{short_name(name)} {item.scores[name]:>3.0f}" for name in CRITERIA_ORDER)
            lines.append(f"  {offer_id} {scored.offer.company.name}")
            lines.append(f"    with    {scored.total:5.1f}  ({detail(scored)})")
            lines.append(f"    without {after.total:5.1f}  ({detail(after)})")
        lines.append("")
    write_csv(output_dir / "e3_rank_reversal.csv", header, rows)
    write_text(output_dir / "e3_rank_reversal.txt", lines)
    return lines


@experiment("E6")
def booking_consistency(data, output_dir):
    """Book up to the last seat, try once more, restart, and check what was kept.

    Uses a temporary booking file and a seeded random generator, so the real
    bookings are never touched and the references are the same on every run.
    """
    profile = data.profiles["business"]
    _, ranking = data.rank(profile)
    offer = ranking[0].offer
    booked_at = datetime(2026, 7, 1, 12, 0)
    steps = []

    def record(step, expected, actual):
        steps.append([step, expected, actual, "pass" if str(expected) == str(actual) else "FAIL"])

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "bookings.json"
        store = BookingStore(path, rng=random.Random(4420))
        start = store.seats_left(offer)
        record("seats left before booking", offer.available_seats, start)

        first = store.book(offer, start - 1, profile.name, booked_at=booked_at)
        record(f"book {start - 1} seats", 1, store.seats_left(offer))
        last = store.book(offer, 1, profile.name, booked_at=booked_at)
        record("book the last seat", 0, store.seats_left(offer))

        try:
            store.book(offer, 1, profile.name, booked_at=booked_at)
            outcome = "booked"
        except BookingError:
            outcome = "refused"
        record("try one more seat", "refused", outcome)
        record("bookings saved after refusal", 2, len(BookingStore(path).bookings))

        restarted = BookingStore(path)
        record("seats left after restart", 0, restarted.seats_left(offer))
        record("references unique", True, len(restarted.references()) == 2)
        saved = restarted.find(first.reference)
        record("fare conditions stored", offer.fare.describe(), saved.fare.describe())
        record("offer data unchanged", start, offer.available_seats)

        filtered = filter_offers(data.offers, constraints_for(profile, restarted.seats_left))
        record("sold-out offer still in ranking", False, offer in filtered.accepted)

    header = ["step", "expected", "actual", "result"]
    passed = sum(1 for step in steps if step[3] == "pass")
    lines = [
        "E6 Booking consistency",
        f"Offer: {offer.offer_id} {offer.company.name} {offer.fare.fare_type}, "
        f"{offer.available_seats} seats, business profile",
        f"References: {first.reference}, {last.reference}",
        "",
    ]
    lines += [f"  {step:<36} expected {expected!s:<28} got {actual!s:<28} {result}"
              for step, expected, actual, result in steps]
    lines += ["", f"{passed} of {len(steps)} checks passed"]
    write_csv(output_dir / "e6_booking_consistency.csv", header, steps)
    write_text(output_dir / "e6_booking_consistency.txt", lines)
    return lines
