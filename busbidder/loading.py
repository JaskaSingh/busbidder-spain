"""Reading the data files into model objects.

Reference files (companies and destinations) must be completely valid. A bad
row there stops loading with a DataFileError, because every offer depends on
them. Offer files are handled row by row (added in the next step).
"""

import csv

from .errors import DataFileError, InvalidValueError
from .models import Company, Destination
from .validation import clean_code, parse_yes_no, require_text, to_int

COMPANY_COLUMNS = ["company_id", "name", "profile"]
DESTINATION_COLUMNS = ["destination_id", "name", "distance_km", "coastal"]


def read_rows(path, required_columns):
    """Return (line_number, row) pairs from a CSV file.

    Raises DataFileError if the file is missing, unreadable, empty or lacks a
    required column. Line numbers match what an editor shows, so the header
    is line 1 and the first data row is line 2.
    """
    try:
        with open(path, newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            if reader.fieldnames is None:
                raise DataFileError(path, "file is empty")
            missing = [column for column in required_columns if column not in reader.fieldnames]
            if missing:
                raise DataFileError(path, f"missing column(s): {', '.join(missing)}")
            return [(reader.line_num, row) for row in reader]
    except FileNotFoundError:
        raise DataFileError(path, "file not found") from None
    except (OSError, UnicodeDecodeError) as error:
        raise DataFileError(path, f"could not be read ({error})") from None
    except csv.Error as error:
        raise DataFileError(path, f"is not valid CSV ({error})") from None


def _load_reference(path, columns, id_field, build):
    """Load a reference file into a dictionary keyed by ID.

    Any invalid or duplicate row raises DataFileError naming the line.
    """
    items = {}
    for line, row in read_rows(path, columns):
        try:
            item_id = clean_code(id_field, row[id_field])
            if item_id in items:
                raise InvalidValueError(id_field, item_id, "appears more than once")
            items[item_id] = build(item_id, row)
        except InvalidValueError as error:
            raise DataFileError(path, f"line {line}: {error}") from None
    return items


def load_companies(path):
    def build(company_id, row):
        return Company(
            company_id,
            require_text("name", row["name"]),
            require_text("profile", row["profile"]),
        )

    return _load_reference(path, COMPANY_COLUMNS, "company_id", build)


def load_destinations(path):
    def build(destination_id, row):
        return Destination(
            destination_id,
            require_text("name", row["name"]),
            to_int("distance_km", row["distance_km"]),
            parse_yes_no("coastal", row["coastal"]),
        )

    return _load_reference(path, DESTINATION_COLUMNS, "destination_id", build)
