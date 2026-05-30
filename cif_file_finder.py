"""Backward-compatible entry point; logic lives in pyads.cif_finder."""

from pyads.cif_finder import main  # noqa: F401
from pyads.cif_finder import *  # noqa: F401, F403

if __name__ == "__main__":
    main()
