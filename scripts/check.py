"""Run the same checks locally and in CI."""

import subprocess
import sys

from app.config import ROOT


def main() -> None:
    checks = [
        ["ruff", "check", "app", "tests", "scripts"],
        ["ruff", "format", "--check", "app", "tests", "scripts"],
        ["pytest", "-q"],
        ["scripts.evaluate", "--check", "docs/evaluation.json"],
    ]
    for arguments in checks:
        print(f"Checking: {' '.join(arguments)}", flush=True)
        subprocess.run([sys.executable, "-m", *arguments], cwd=ROOT, check=True)
    print("All verification checks passed.", flush=True)


if __name__ == "__main__":
    main()
