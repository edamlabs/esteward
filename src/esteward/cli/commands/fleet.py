"""`esteward fleet`: the projects under maintenance, as the JSON list a workflow matrix consumes."""

import sys

import msgspec

from esteward.core.settings import settings as st


def fleet() -> None:
    """Print the fleet entries (file stems of `fleet/*.toml`) as a compact JSON array."""
    entries = sorted(path.stem for path in st.fleet_dir.glob("*.toml"))
    sys.stdout.write(msgspec.json.encode(entries).decode() + "\n")
