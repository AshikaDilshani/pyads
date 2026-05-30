"""Console entry point for pyads (alias for pyads.runner).

This file exists for users who prefer `python cli.py` over `python runner.py`.
All pipeline logic lives in pyads.runner.
"""

from pyads.runner import main

if __name__ == "__main__":
    main()
