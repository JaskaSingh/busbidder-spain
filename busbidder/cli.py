"""Command-line interface.

    python3 -m busbidder rank --profile budget
    python3 -m busbidder compare --profiles budget business flexible
    python3 -m busbidder book --profile business
    python3 -m busbidder --offers data/offers_invalid.csv validate
    python3 -m busbidder experiments --output results

Every command loads the data, does its work and prints a summary. Expected
problems (missing files, invalid profiles, unknown names) are caught here,
shown as one clear line and logged with full detail. Exit codes: 0 success,
1 expected error, 2 invalid command-line arguments (from argparse).
"""

import argparse
import logging
import sys
from pathlib import Path

from .booking import DEFAULT_BOOKINGS_PATH, BookingStore
from .errors import BusBidderError, ConfigError
from .experiments import EXPERIMENTS, ExperimentData, run_experiments
from .explain import explain_top
from .filtering import constraints_for, filter_offers
from .loading import load_companies, load_destinations, load_offers
from .logging_setup import DEFAULT_LOG_DIR, configure_logging
from .profiles import load_profiles
from .reporting import format_booking, format_load_result, format_profile, format_ranking
from .scoring import DEFAULT_STRATEGY, STRATEGIES, rank_offers

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1


def positive_int(text):
    """argparse type: a whole number of at least 1."""
    try:
        number = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, not {number}")
    return number


def build_parser():
    parser = argparse.ArgumentParser(
        prog="python3 -m busbidder",
        description="Filter and rank simulated bus offers from Madrid for a traveller profile.",
    )
    parser.add_argument("--data-dir", type=Path, default=Path("data"),
                        help="folder with companies.csv, destinations.csv and offers.csv (default: data)")
    parser.add_argument("--profiles-file", type=Path, default=Path("config") / "profiles.json",
                        help="traveller profiles (default: config/profiles.json)")
    parser.add_argument("--bookings", type=Path, default=DEFAULT_BOOKINGS_PATH,
                        help=f"booking file (default: {DEFAULT_BOOKINGS_PATH})")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR,
                        help=f"folder for busbidder.log (default: {DEFAULT_LOG_DIR})")
    parser.add_argument("--offers", type=Path, default=None,
                        help="offer file to use instead of DATA_DIR/offers.csv")

    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    strategies = STRATEGIES.names()  # discovered from the registry

    rank = commands.add_parser("rank", help="rank offers for one profile")
    rank.add_argument("--profile", required=True, help="profile name from the profiles file")
    rank.add_argument("--strategy", choices=strategies, default=DEFAULT_STRATEGY)
    rank.add_argument("--top", type=positive_int, default=10, help="number of offers to show (default: 10)")
    rank.set_defaults(handler=command_rank)

    compare = commands.add_parser("compare", help="compare the winners of several profiles")
    compare.add_argument("--profiles", nargs="+", required=True, metavar="NAME")
    compare.add_argument("--strategy", choices=strategies, default=DEFAULT_STRATEGY)
    compare.add_argument("--top", type=positive_int, default=3, help="offers shown per profile (default: 3)")
    compare.set_defaults(handler=command_compare)

    book = commands.add_parser("book", help="rank offers for a profile, then choose one and book it")
    book.add_argument("--profile", required=True, help="profile name from the profiles file")
    book.add_argument("--strategy", choices=strategies, default=DEFAULT_STRATEGY)
    book.add_argument("--top", type=positive_int, default=5, help="offers to choose from (default: 5)")
    book.set_defaults(handler=command_book)

    validate = commands.add_parser("validate", help="check an offer file and list every problem")
    validate.set_defaults(handler=command_validate)

    experiments = commands.add_parser(
        "experiments", help="run the experiments and write their tables to an output folder"
    )
    experiments.add_argument("--output", type=Path, default=Path("results"),
                             help="folder for result files (default: results)")
    experiments.add_argument("--only", nargs="+", choices=EXPERIMENTS.names(), metavar="NAME",
                             help=f"run only these experiments ({', '.join(EXPERIMENTS.names())})")
    experiments.set_defaults(handler=command_experiments)

    return parser


class Context:
    """Everything a command needs, loaded once."""

    def __init__(self, args, need_profiles=True, need_bookings=True):
        offers_path = args.offers or args.data_dir / "offers.csv"
        self.companies = load_companies(args.data_dir / "companies.csv")
        self.destinations = load_destinations(args.data_dir / "destinations.csv")
        self.load_result = load_offers(offers_path, self.companies, self.destinations)
        self.offers = self.load_result.offers
        self.profiles_path = args.profiles_file
        self.profiles = load_profiles(args.profiles_file) if need_profiles else {}
        # validate and experiments do not use bookings, so they must not
        # depend on the booking file being readable.
        self.store = BookingStore(args.bookings) if need_bookings else None

    def profile(self, name):
        try:
            return self.profiles[name]
        except KeyError:
            available = ", ".join(self.profiles)
            raise ConfigError(self.profiles_path, f"no profile named '{name}' (available: {available})") from None

    def rank_for(self, profile, strategy):
        constraints = constraints_for(profile, self.store.seats_left)
        filtered = filter_offers(self.offers, constraints)
        return filtered, rank_offers(filtered.accepted, profile, strategy)


def command_rank(args):
    context = Context(args)
    profile = context.profile(args.profile)
    filtered, ranking = context.rank_for(profile, args.strategy)

    print(format_profile(profile))
    print(f"Normalisation: {args.strategy}")
    print()
    print(filtered.summary())
    print()
    print(format_ranking(ranking, args.top))
    if ranking:
        print()
        print(explain_top(ranking, profile).text())
    logger.info("Ranked %d offers for profile %s with %s", len(ranking), profile.name, args.strategy)
    return EXIT_OK


def command_compare(args):
    context = Context(args)
    profiles = [context.profile(name) for name in args.profiles]
    print(f"Normalisation: {args.strategy}")
    winners = []
    for profile in profiles:
        filtered, ranking = context.rank_for(profile, args.strategy)
        print()
        print(format_profile(profile))
        print(f"  {filtered.summary()}")
        print(format_ranking(ranking, args.top))
        if ranking:
            print(explain_top(ranking, profile).headline)
            winners.append(ranking[0].offer.offer_id)
    print()
    distinct = len(set(winners))
    print(f"{len(profiles)} profiles, {distinct} different first-ranked offer(s).")
    return EXIT_OK


class Cancelled(Exception):
    """The user chose to stop the booking. Not an error."""


def ask(prompt, input_func):
    """Read one answer. End of input (Ctrl+D) or Ctrl+C cancels the booking."""
    try:
        return input_func(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise Cancelled from None


def ask_number(prompt, low, high, input_func, default=None):
    """Ask until the answer is a whole number from low to high, or q to cancel.

    Empty input uses the default if there is one, otherwise asks again.
    """
    while True:
        answer = ask(prompt, input_func)
        if answer.lower() == "q":
            raise Cancelled
        if answer == "" and default is not None:
            return default
        try:
            number = int(answer)
        except ValueError:
            print(f"Please enter a number from {low} to {high}, or q to cancel.")
            continue
        if not low <= number <= high:
            print(f"{number} is not between {low} and {high}. Please try again.")
            continue
        return number


def ask_yes_no(prompt, input_func):
    while True:
        answer = ask(prompt, input_func).lower()
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no", "q"):
            return False
        print("Please answer y or n.")


def command_book(args, input_func=None):
    """Show the ranking, let the traveller choose an offer and seats, confirm and book."""
    # Look input up when the command runs (not when the module loads), so
    # tests can replace it.
    input_func = input_func or (lambda prompt: input(prompt))
    context = Context(args)
    profile = context.profile(args.profile)
    filtered, ranking = context.rank_for(profile, args.strategy)

    print(format_profile(profile))
    print()
    print(filtered.summary())
    print()
    print(format_ranking(ranking, args.top))
    if not ranking:
        print("Nothing can be booked with these constraints.")
        return EXIT_OK
    print()
    print(explain_top(ranking, profile).text())
    print()

    choices = ranking[:args.top]
    try:
        position = ask_number(
            f"Choose an offer by rank (1 to {len(choices)}), or q to cancel: ",
            1, len(choices), input_func,
        )
        offer = choices[position - 1].offer
        left = context.store.seats_left(offer)
        seats = ask_number(
            f"Seats to book (1 to {left}, Enter for {min(profile.seats_needed, left)}): ",
            1, left, input_func, default=min(profile.seats_needed, left),
        )
        total = seats * offer.price_eur
        print(
            f"\nBook {seats} seat(s) on {offer.offer_id} {offer.company.name} "
            f"{offer.departure:%a %d %b %H:%M} for EUR {total:.2f} ({offer.fare.describe()})?"
        )
        if not ask_yes_no("Confirm (y/n): ", input_func):
            raise Cancelled
    except Cancelled:
        print("Booking cancelled. Nothing was saved.")
        logger.info("Booking cancelled by user for profile %s", profile.name)
        return EXIT_OK

    booking = context.store.book(offer, seats, profile.name)
    print()
    print(format_booking(booking, offer, context.store.seats_left(offer), context.store.path))
    return EXIT_OK


def command_validate(args):
    context = Context(args, need_profiles=False, need_bookings=False)
    print(format_load_result(context.load_result))
    return EXIT_OK


def command_experiments(args):
    context = Context(args, need_bookings=False)
    data = ExperimentData(
        context.companies, context.destinations, context.offers, context.profiles, args.data_dir
    )
    summaries = run_experiments(data, args.output, args.only)
    for name, lines in summaries.items():
        print("\n".join(lines))
    print(f"Results written to {args.output}/")
    logger.info("Ran experiments %s into %s", ", ".join(summaries), args.output)
    return EXIT_OK


def main(argv=None):
    args = build_parser().parse_args(argv)
    log_path = configure_logging(args.log_dir)
    logger.info("Command: %s", " ".join(sys.argv[1:] if argv is None else argv))
    try:
        return args.handler(args)
    except BusBidderError as error:
        # One clear line for the user, full detail in the log.
        print(f"Error: {error}", file=sys.stderr)
        print(f"See {log_path} for details.", file=sys.stderr)
        logger.error("%s: %s", type(error).__name__, error)
        return EXIT_ERROR
