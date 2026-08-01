"""Bootstrap Skillsmith's runtime environment, then run the video helper."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path


def skill_root() -> Path:
    """Return the installed skill directory that contains SKILL.md."""
    return Path(__file__).resolve().parents[1]


def venv_python(venv_dir: Path) -> Path:
    """Return the Python executable path inside a virtual environment."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def requirements_hash(requirements_path: Path) -> str:
    """Hash the dependency file so installs rerun only when requirements change."""
    return hashlib.sha256(requirements_path.read_bytes()).hexdigest()


def ensure_venv(root: Path) -> Path:
    """Create or update Skillsmith's local virtual environment."""
    venv_dir = root / ".venv"
    python = venv_python(venv_dir)
    requirements = root / "scripts" / "requirements.txt"
    marker = venv_dir / ".skillsmith-requirements.sha256"

    if not requirements.is_file():
        raise FileNotFoundError(f"Missing requirements file: {requirements}")

    if not python.exists():
        venv.create(venv_dir, with_pip=True)

    expected_hash = requirements_hash(requirements)
    installed_hash = marker.read_text(encoding="utf-8").strip() if marker.exists() else ""

    if installed_hash != expected_hash:
        subprocess.check_call(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "-r",
                str(requirements),
            ]
        )
        marker.write_text(expected_hash + "\n", encoding="utf-8")

    return python


def main(argv: list[str] | None = None) -> int:
    """Prepare dependencies and forward all arguments to scripts/main.py."""
    args = sys.argv[1:] if argv is None else argv
    root = skill_root()
    processor = root / "scripts" / "main.py"

    if not processor.is_file():
        print(f"error: Missing video helper: {processor}", file=sys.stderr)
        return 2

    try:
        python = ensure_venv(root)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"error: Could not prepare Skillsmith environment: {error}", file=sys.stderr)
        return 2

    return subprocess.call([str(python), str(processor), *args])


if __name__ == "__main__":
    raise SystemExit(main())
