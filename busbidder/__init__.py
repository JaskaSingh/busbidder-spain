"""BusBidder Spain: filtering and weighted ranking of bus offers."""

import logging

# Library code only creates log records. The entry point decides where they
# go (see logging_setup.configure_logging). The NullHandler stops Python
# from printing warnings to the terminal when nothing has been configured,
# for example while the tests run.
logging.getLogger(__name__).addHandler(logging.NullHandler())
