"""The esteward command line: the only module that knows the app; every command is registered here."""

import sys

from cyclopts import App

from esteward.cli.commands.fleet import fleet
from esteward.cli.commands.run import run
from esteward.core.logger import setup_logger
from esteward.core.settings import settings as st

app = App(name="esteward", help="Self-maintenance engine of EDamLabs projects.")
app.command(fleet)
app.command(run)


def main() -> None:
    """Entry point: configure logging once, then dispatch the command."""
    setup_logger(st.env, st.log_level)
    app(sys.argv[1:])
