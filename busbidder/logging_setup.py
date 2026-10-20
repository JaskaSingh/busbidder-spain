"""Log file configuration, called once by the entry point.

Levels used across the application:
- INFO: files loaded with counts, corrections, bookings
- WARNING: rejected rows and offers set aside for review
- ERROR: failures that stop a command, such as a missing file
"""

import logging
from pathlib import Path

LOG_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
DEFAULT_LOG_DIR = Path("logs")
LOG_FILE_NAME = "busbidder.log"


def configure_logging(log_dir=DEFAULT_LOG_DIR, level=logging.INFO):
    """Send the application's log records to log_dir/busbidder.log.

    Safe to call more than once: an existing file handler for the same file
    is reused, so lines are never written twice. Returns the log file path.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = (log_dir / LOG_FILE_NAME).resolve()

    logger = logging.getLogger("busbidder")
    logger.setLevel(level)
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == log_path:
            return log_path

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    return log_path


def close_logging():
    """Remove and close file handlers. Used by tests and at program exit."""
    logger = logging.getLogger("busbidder")
    for handler in list(logger.handlers):
        if isinstance(handler, logging.FileHandler):
            logger.removeHandler(handler)
            handler.close()
