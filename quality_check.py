"""Run pylint, pycodestyle, and pydocstyle on the full project and report results.

Checks are applied to:
- The ``pyads/`` package (all modules).
- Root-level scripts: runner.py, extractor.py, cif_file_finder.py,
  cif_file_analyzer.py, test.py, quality_check.py.
"""

from __future__ import annotations

import subprocess
import sys


# Root-level scripts that are part of the public surface.
_ROOT_SCRIPTS = [
    "runner.py",
    "extractor.py",
    "cif_file_finder.py",
    "cif_file_analyzer.py",
    "test.py",
    "quality_check.py",
]

CHECKS = [
    (["python", "-m", "pylint", "pyads/"] + _ROOT_SCRIPTS, "pylint"),
    (["python", "-m", "pycodestyle", "pyads/"] + _ROOT_SCRIPTS, "pycodestyle"),
    (["python", "-m", "pydocstyle", "pyads/"] + _ROOT_SCRIPTS, "pydocstyle"),
]


def run_check(cmd: list[str]) -> tuple[int, str]:
    """Run a lint command and return its exit code and combined output."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout + result.stderr


def main() -> None:
    """Run all lint tools and exit with a non-zero code if any tool reports issues."""
    failed: list[str] = []

    for cmd, name in CHECKS:
        print(f"\n{'=' * 60}")
        print(f"  {name}")
        print("=" * 60)
        code, output = run_check(cmd)
        print(output or "(no output)")
        if code != 0:
            failed.append(name)

    print("\n" + "=" * 60)
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("All quality checks passed.")


if __name__ == "__main__":
    main()
