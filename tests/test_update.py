from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest


SCRIPT_PATH = (
    Path(__file__).parents[1] / "skills" / "skillsmith" / "scripts" / "run.py"
)
SPEC = importlib.util.spec_from_file_location("skillsmith_run", SCRIPT_PATH)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = runner
SPEC.loader.exec_module(runner)


def make_installed_skill(root: Path, version: str = "1.0.0") -> None:
    root.mkdir()
    (root / "VERSION").write_text(version + "\n", encoding="utf-8")
    (root / "SKILL.md").write_text("# old\n", encoding="utf-8")
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text("# old\n", encoding="utf-8")
    venv = root / ".venv"
    venv.mkdir()
    (venv / "keep.txt").write_text("keep\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1.2.3", (1, 2, 3)), ("v10.20.30\n", (10, 20, 30))],
)
def test_parse_version(value: str, expected: tuple[int, int, int]) -> None:
    assert runner.parse_version(value) == expected


def test_update_check_reports_once_per_24_hours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    root = tmp_path / "skillsmith"
    make_installed_skill(root)
    calls = 0

    def fetch_version(url: str, timeout: float = 3) -> str:
        nonlocal calls
        calls += 1
        return "1.1.0\n"

    monkeypatch.setattr(runner, "fetch_text", fetch_version)

    runner.maybe_check_update(root)
    runner.maybe_check_update(root)

    assert calls == 1
    notice = capsys.readouterr().err
    assert "Skillsmith 1.1.0 is available" in notice
    assert "python scripts/run.py --update" in notice


def test_failed_update_check_never_interrupts_processing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "skillsmith"
    make_installed_skill(root)

    def fail(url: str, timeout: float = 3) -> str:
        raise OSError("offline")

    monkeypatch.setattr(runner, "fetch_text", fail)
    runner.maybe_check_update(root)


def test_update_from_main_preserves_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "skillsmith"
    make_installed_skill(root)

    def create_archive(url: str, destination: Path) -> None:
        prefix = "skillsmith-main/skills/skillsmith/"
        with zipfile.ZipFile(destination, "w") as archive:
            archive.writestr(prefix + "VERSION", "1.1.0\n")
            archive.writestr(prefix + "SKILL.md", "# new\n")
            archive.writestr(prefix + "scripts/run.py", "# new\n")

    monkeypatch.setattr(runner, "download_file", create_archive)

    assert runner.update_from_main(root) == "1.1.0"
    assert (root / "VERSION").read_text(encoding="utf-8") == "1.1.0\n"
    assert (root / "SKILL.md").read_text(encoding="utf-8") == "# new\n"
    assert (root / "scripts" / "run.py").read_text(encoding="utf-8") == "# new\n"
    assert (root / ".venv" / "keep.txt").read_text(encoding="utf-8") == "keep\n"


def test_update_command_does_not_bootstrap_video_dependencies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    root = tmp_path / "skillsmith"
    make_installed_skill(root)
    monkeypatch.setattr(runner, "skill_root", lambda: root)
    monkeypatch.setattr(runner, "update_from_main", lambda installed: "1.1.0")

    def unexpected_bootstrap(installed: Path) -> Path:
        raise AssertionError("ensure_venv must not run for --update")

    monkeypatch.setattr(runner, "ensure_venv", unexpected_bootstrap)

    assert runner.main(["--update"]) == 0
    assert "Updated Skillsmith to 1.1.0" in capsys.readouterr().out
