"""Run pylint, pycodestyle, and pydocstyle on the pyads package and report results."""

from __future__ import annotations

import subprocess
import sys


CHECKS = [
    (["python", "-m", "pylint", "pyads/"], "pylint"),
    (["python", "-m", "pycodestyle", "pyads/"], "pycodestyle"),
    (["python", "-m", "pydocstyle", "pyads/"], "pydocstyle"),
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
