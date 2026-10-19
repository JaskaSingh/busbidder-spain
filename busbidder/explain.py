"""Plain-language explanation of why an offer ranked first.

The explanation is generated from the scores, not written by hand. For each
weighted criterion it compares the top offer with the average of the other
accepted offers and weighs the difference by the traveller's weight.

- Advantages: up to two criteria where the top offer gains the most points
  over the alternatives and also scores at least 50 on its own.
- Disadvantages: criteria where it is worse than the alternatives, and
  criteria where it scores under 50 even if the others are worse still.
  At most two are shown, and at least one is always named, so remaining
  drawbacks are never hidden.

Wording always says "ranked first under your preferences", never "best",
because the result depends on the chosen constraints, weights and data.
"""

from dataclasses import dataclass, field

from .criteria import minutes_outside_window
from .scoring import CLOSE_MARGIN_POINTS

# A criterion score of at least this counts as good on its own.
GOOD_SCORE = 50


def format_minutes(minutes):
    hours, rest = divmod(int(round(minutes)), 60)
    return f"{hours} h {rest:02d} min"


def _price_fact(offer, profile):
    return f"costs EUR {offer.price_eur:.2f} of your EUR {profile.max_price_eur:.2f} budget"


def _duration_fact(offer, profile):
    return f"takes {format_minutes(offer.duration_minutes)}"


def _departure_fact(offer, profile):
    start = profile.preferred_departure_from.strftime("%H:%M")
    end = profile.preferred_departure_to.strftime("%H:%M")
    outside = minutes_outside_window(
        offer.departure.time(), profile.preferred_departure_from, profile.preferred_departure_to
    )
    when = offer.departure.strftime("%a %d %b %H:%M")
    if outside == 0:
        return f"leaves {when}, inside your preferred window {start} to {end}"
    return f"leaves {when}, {format_minutes(outside)} outside your preferred window {start} to {end}"


def _flexibility_fact(offer, profile):
    return f"has a {offer.fare.fare_type} ticket ({offer.fare.describe()})"


# Concrete facts for the four required criteria. A criterion added later
# without an entry here still gets a generic sentence with its score.
FACTS = {
    "price": _price_fact,
    "duration": _duration_fact,
    "departure_time": _departure_fact,
    "flexibility": _flexibility_fact,
}


def describe_criterion(name, scored, profile):
    fact = FACTS.get(name)
    if fact is None:
        return f"scores {scored.scores[name]:.0f} of 100 on {name}"
    return fact(scored.offer, profile)


@dataclass
class Explanation:
    headline: str
    advantages: list = field(default_factory=list)
    disadvantages: list = field(default_factory=list)
    margin_note: str = ""

    def lines(self):
        result = [self.headline]
        result += [f"  + {text}" for text in self.advantages]
        result += [f"  - {text}" for text in self.disadvantages]
        if self.margin_note:
            result.append(f"  {self.margin_note}")
        return result

    def text(self):
        return "\n".join(self.lines())


def explain_top(ranking, profile):
    """Explain the first offer in a ranking. Returns None for an empty ranking."""
    if not ranking:
        return None
    top, others = ranking[0], ranking[1:]
    offer = top.offer
    weighted = [name for name, weight in profile.weights.items() if weight > 0]

    headline = (
        f"{offer.company.name} {offer.offer_id} ranked first under your preferences "
        f"with {top.total:.1f} of 100 points."
    )

    if not others:
        weakest = min(weighted, key=lambda name: top.scores[name])
        return Explanation(
            headline=headline,
            advantages=["It is the only offer that meets all your hard constraints."],
            disadvantages=[f"Weakest point: it {describe_criterion(weakest, top, profile)}."],
        )

    # How much each criterion helps or hurts compared with the other offers,
    # in points of the total score.
    average = {
        name: sum(other.scores[name] for other in others) / len(others) for name in weighted
    }
    effect = {
        name: profile.weights[name] * (top.scores[name] - average[name]) / 100
        for name in weighted
    }

    def sentence(name):
        label = name.replace("_", " ")
        return (
            f"It {describe_criterion(name, top, profile)}. Scores {top.scores[name]:.0f} "
            f"on {label}, against an average of {average[name]:.0f} for the other offers."
        )

    by_effect = sorted(weighted, key=lambda name: effect[name], reverse=True)
    advantage_names = [
        name for name in by_effect
        if effect[name] > 0 and top.scores[name] >= GOOD_SCORE
    ][:2]

    worse_than_others = [name for name in reversed(by_effect) if effect[name] < 0]
    weak_on_its_own = sorted(
        (name for name in weighted if top.scores[name] < GOOD_SCORE),
        key=lambda name: top.scores[name],
    )
    disadvantage_names = []
    for name in worse_than_others + weak_on_its_own:
        if name not in disadvantage_names and name not in advantage_names:
            disadvantage_names.append(name)
    if not disadvantage_names:
        remaining = [name for name in weighted if name not in advantage_names] or weighted
        disadvantage_names = [min(remaining, key=lambda name: top.scores[name])]

    advantages = [sentence(name) for name in advantage_names]
    disadvantages = [sentence(name) for name in disadvantage_names[:2]]

    second = others[0]
    lead = top.total - second.total
    if lead < CLOSE_MARGIN_POINTS:
        margin_note = (
            f"Close call: only {lead:.1f} points ahead of {second.offer.company.name} "
            f"{second.offer.offer_id}. Small changes to your weights could reverse the order."
        )
    else:
        margin_note = f"{lead:.1f} points ahead of {second.offer.company.name} {second.offer.offer_id}."

    return Explanation(headline, advantages, disadvantages, margin_note)
