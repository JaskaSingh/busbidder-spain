"""Command-line interface.

    python3 -m busbidder rank --profile budget
    python3 -m busbidder compare --profiles budget business flexible
    python3 -m busbidder validate --offers data/offers_invalid.csv

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
from .explain import explain_top
from .filtering import constraints_for, filter_offers
from .loading import load_companies, load_destinations, load_offers
from .logging_setup import DEFAULT_LOG_DIR, configure_logging
from .profiles import load_profiles
from .reporting import format_load_result, format_profile, format_ranking
from .scoring import DEFAULT_STRATEGY, STRATEGIES, rank_offers

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1


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
    rank.add_argument("--top", type=int, default=10, help="number of offers to show (default: 10)")
    rank.set_defaults(handler=command_rank)

    compare = commands.add_parser("compare", help="compare the winners of several profiles")
    compare.add_argument("--profiles", nargs="+", required=True, metavar="NAME")
    compare.add_argument("--strategy", choices=strategies, default=DEFAULT_STRATEGY)
    compare.add_argument("--top", type=int, default=3, help="offers shown per profile (default: 3)")
    compare.set_defaults(handler=command_compare)

    validate = commands.add_parser("validate", help="check an offer file and list every problem")
    validate.set_defaults(handler=command_validate)

    return parser


class Context:
    """Everything a command needs, loaded once."""

    def __init__(self, args, need_profiles=True):
        offers_path = args.offers or args.data_dir / "offers.csv"
        self.companies = load_companies(args.data_dir / "companies.csv")
        self.destinations = load_destinations(args.data_dir / "destinations.csv")
        self.load_result = load_offers(offers_path, self.companies, self.destinations)
        self.offers = self.load_result.offers
        self.profiles_path = args.profiles_file
        self.profiles = load_profiles(args.profiles_file) if need_profiles else {}
        self.store = BookingStore(args.bookings)

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


def command_validate(args):
    context = Context(args, need_profiles=False)
    print(format_load_result(context.load_result))
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
