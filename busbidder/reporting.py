"""Turning results into text for the terminal.

These functions only build strings. Printing and file writing happen in the
CLI, so the formatting can be tested without capturing output.
"""

from .explain import format_minutes

CRITERION_SHORT = {"price": "Price", "duration": "Dur", "departure_time": "Time", "flexibility": "Flex"}


def short_name(criterion):
    return CRITERION_SHORT.get(criterion, criterion[:5].title())


def format_profile(profile):
    window = (
        f"{profile.preferred_departure_from:%H:%M} to {profile.preferred_departure_to:%H:%M}"
    )
    weights = ", ".join(f"{name} {weight}%" for name, weight in profile.weights.items())
    hard = [
        f"Madrid to {profile.destination_id}",
        f"departing {profile.earliest_date} to {profile.latest_date}",
        f"max EUR {profile.max_price_eur:.2f} per seat",
        f"{profile.seats_needed} seat(s)",
        f"max {profile.max_transfers} transfer(s)",
    ]
    if profile.min_change_level != "none":
        hard.append(f"change level at least '{profile.min_change_level}'")
    if profile.max_duration_minutes is not None:
        hard.append(f"max {format_minutes(profile.max_duration_minutes)}")
    return "\n".join([
        f"Profile: {profile.label} ({profile.name})",
        f"  Hard constraints: {', '.join(hard)}",
        f"  Preferences: departure {window}. Weights: {weights}",
    ])


def format_ranking(ranking, top=10):
    """A table of the ranked offers with criterion scores and total."""
    if not ranking:
        return "No offers meet all hard constraints."
    criteria = list(ranking[0].scores)
    header = (
        f"{'#':>2}  {'Offer':<9} {'Company':<15} {'Fare':<8} {'Departure':<12} "
        f"{'Duration':>11} {'Price':>8} {'Tr':>2}  "
        + " ".join(f"{short_name(c):>5}" for c in criteria)
        + f"  {'Total':>5}"
    )
    lines = [header, "-" * len(header)]
    for scored in ranking[:top]:
        offer = scored.offer
        lines.append(
            f"{scored.rank:>2}  {offer.offer_id:<9} {offer.company.name:<15} "
            f"{offer.fare.fare_type:<8} {offer.departure:%d %b %H:%M}  "
            f"{format_minutes(offer.duration_minutes):>11} {offer.price_eur:>8.2f} {offer.transfers:>2}  "
            + " ".join(f"{scored.scores[c]:>5.0f}" for c in criteria)
            + f"  {scored.total:>5.1f}"
        )
    if len(ranking) > top:
        lines.append(f"... {len(ranking) - top} more offer(s) not shown.")
    return "\n".join(lines)


def format_load_result(result):
    lines = [f"Offers: {result.summary()}."]
    for title, issues in (("Rejected", result.rejected), ("Set aside for review", result.review)):
        if issues:
            lines.append(f"{title}:")
            lines += [
                f"  line {i.line:>3}  {i.offer_id or '?':<10} {i.field}: {i.value!r} {i.reason}"
                for i in issues
            ]
    if result.corrections:
        lines.append("Corrected:")
        lines += [
            f"  line {c.line:>3}  {c.offer_id:<10} {c.field}: {c.original!r} to {c.corrected!r}"
            for c in result.corrections
        ]
    return "\n".join(lines)
