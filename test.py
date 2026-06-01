"""Offline test runner — discovers and runs all tests in the tests/ directory."""

from __future__ import annotations

import unittest
from pathlib import Path


def main() -> int:
    """Discover and run all offline unit tests; return 0 on success."""
    project_root = Path(__file__).resolve().parent
    suite = unittest.defaultTestLoader.discover(str(project_root / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
