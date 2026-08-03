"""Bootstrap Skillsmith's runtime environment, then run the video helper."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import venv
import zipfile
from pathlib import Path


VERSION_URL = (
    "https://raw.githubusercontent.com/adityas2410/skillsmith/"
    "main/skills/skillsmith/VERSION"
)
ARCHIVE_URL = "https://github.com/adityas2410/skillsmith/archive/refs/heads/main.zip"
CHECK_INTERVAL_SECONDS = 24 * 60 * 60
NETWORK_TIMEOUT_SECONDS = 3


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


def parse_version(value: str) -> tuple[int, int, int]:
    """Parse a three-part numeric version, optionally prefixed with v."""
    parts = value.strip().removeprefix("v").split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"Invalid Skillsmith version: {value!r}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def read_version(root: Path) -> str:
    """Read and validate a skill folder's VERSION file."""
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    parse_version(version)
    return version


def fetch_text(url: str, timeout: float = NETWORK_TIMEOUT_SECONDS) -> str:
    """Fetch a short UTF-8 text file from GitHub."""
    request = urllib.request.Request(url, headers={"User-Agent": "Skillsmith"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def maybe_check_update(root: Path) -> None:
    """Report a newer main-branch version at most once every 24 hours."""
    marker = root / ".venv" / ".skillsmith-update-check"
    try:
        if marker.exists() and time.time() - marker.stat().st_mtime < CHECK_INTERVAL_SECONDS:
            return
        marker.touch()
        installed = read_version(root)
        latest = fetch_text(VERSION_URL).strip()
        if parse_version(latest) > parse_version(installed):
            print(
                f"Skillsmith {latest} is available. Installed: {installed}.\n"
                "Run: python scripts/run.py --update",
                file=sys.stderr,
            )
    except Exception:
        return


def download_file(url: str, destination: Path) -> None:
    """Download a file from GitHub to a local path."""
    request = urllib.request.Request(url, headers={"User-Agent": "Skillsmith"})
    with urllib.request.urlopen(request, timeout=60) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output)


def update_from_main(root: Path) -> str:
    """Overlay the latest main-branch skill files, leaving .venv untouched."""
    with tempfile.TemporaryDirectory(prefix="skillsmith-update-") as temp_name:
        temp = Path(temp_name)
        archive = temp / "main.zip"
        download_file(ARCHIVE_URL, archive)
        with zipfile.ZipFile(archive) as source:
            source.extractall(temp / "source")

        matches = list((temp / "source").glob("*/skills/skillsmith"))
        if len(matches) != 1:
            raise ValueError("Downloaded repository does not contain Skillsmith")
        released = matches[0]
        latest = read_version(released)

        files = [path for path in released.rglob("*") if path.is_file()]
        files.sort(key=lambda path: path.name == "VERSION")
        for source_path in files:
            relative = source_path.relative_to(released)
            if ".venv" in relative.parts:
                continue
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination)

    return latest


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

    if args == ["--update"]:
        try:
            version = update_from_main(root)
        except Exception as error:
            print(f"error: Could not update Skillsmith: {error}", file=sys.stderr)
            return 2
        print(f"Updated Skillsmith to {version}. The existing .venv was preserved.")
        return 0

    processor = root / "scripts" / "main.py"

    if not processor.is_file():
        print(f"error: Missing video helper: {processor}", file=sys.stderr)
        return 2

    try:
        python = ensure_venv(root)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"error: Could not prepare Skillsmith environment: {error}", file=sys.stderr)
        return 2

    maybe_check_update(root)
    return subprocess.call([str(python), str(processor), *args])


if __name__ == "__main__":
    raise SystemExit(main())
