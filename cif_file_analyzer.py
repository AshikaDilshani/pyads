"""Backward-compatible entry point; logic lives in pyads.cif_analyzer."""

from pyads.cif_analyzer import main  # noqa: F401
from pyads.cif_analyzer import *  # noqa: F401, F403

if __name__ == "__main__":
    main()
