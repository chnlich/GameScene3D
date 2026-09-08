"""Reproduce dependency installation, offline plumbing tests, and real HTTP startup."""
import shutil
import subprocess
from pathlib import Path

from server.files import ROOT


def main():
    if Path.cwd().resolve() != ROOT:
        raise RuntimeError("Run the validation recipe from the repository root")
    for executable in ("uv", "npm", "git"):
        if shutil.which(executable) is None:
            raise RuntimeError(f"Required launcher {executable} is missing")
    locks = {name: (ROOT / name).read_bytes() for name in ("uv.lock", "package-lock.json")}
    subprocess.run(["uv", "sync", "--locked"], check=True)
    subprocess.run(["npm", "ci", "--ignore-scripts"], check=True)
    (ROOT / "runtime").mkdir(exist_ok=True)
    subprocess.run(["uv", "run", "--locked", "python", "-m", "pytest", "-q", "--basetemp", "runtime/pytest"], check=True)
    subprocess.run(["uv", "run", "--locked", "python", "-m", "server.tests.smoke"], check=True)
    for name, before in locks.items():
        if (ROOT / name).read_bytes() != before:
            raise RuntimeError(f"Reproducibility check changed {name}")
    subprocess.run(["git", "diff", "--check"], check=True)


if __name__ == "__main__":
    main()
