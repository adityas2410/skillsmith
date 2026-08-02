from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest


SCRIPT_PATH = (
    Path(__file__).parents[1] / "skills" / "skillsmith" / "scripts" / "main.py"
)
SPEC = importlib.util.spec_from_file_location("skillsmith_video", SCRIPT_PATH)
assert SPEC and SPEC.loader
video = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = video
SPEC.loader.exec_module(video)


def make_test_video(path: Path) -> None:
    """Create three visual states, each repeated once to test deduplication."""
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        4.0,
        (160, 90),
    )
    if not writer.isOpened():
        pytest.skip("MJPG video encoding is unavailable")

    # At four frames per second, these six frames make a 1.5-second video:
    #   1-2: unchanged light screen
    #   3-4: light screen with a large red rectangle
    #   5-6: unchanged green screen
    # Each duplicated state gives the selector an obvious frame to discard.
    states = [
        ((245, 245, 245), None),
        ((245, 245, 245), None),
        ((245, 245, 245), (20, 20, 140, 70)),
        ((245, 245, 245), (20, 20, 140, 70)),
        ((40, 170, 40), None),
        ((40, 170, 40), None),
    ]
    for background, box in states:
        frame = np.full((90, 160, 3), background, dtype=np.uint8)
        if box:
            x1, y1, x2, y2 = box
            cv2.rectangle(frame, (x1, y1), (x2, y2), (20, 20, 220), -1)
        writer.write(frame)
    writer.release()


def make_selected_frame(index: int, color: tuple[int, int, int]):
    """Create a full-color selected frame without video compression."""
    frame = np.full((90, 160, 3), color, dtype=np.uint8)
    return video.SelectedFrame(
        source_frame_index=index - 1,
        timestamp_seconds=float(index - 1),
        png_bytes=video.encode_png(frame),
        comparison=video.make_comparison_frame(frame),
        reasons=["layout-change"],
        scores=None,
        is_first=index == 1,
    )


def test_candidate_indices_include_first_and_final() -> None:
    """Sampling must cover both video boundaries even when using an interval."""
    metadata = video.VideoMetadata(10.0, 2.1, 21, 100, 100)
    assert video.candidate_frame_indices(metadata, 0.5) == [0, 5, 10, 15, 20]


def test_static_frames_are_near_duplicates() -> None:
    """Two identical pictures must produce zero visual-difference scores."""
    frame = np.full((80, 120, 3), (20, 80, 140), dtype=np.uint8)
    left = video.make_comparison_frame(frame)
    right = video.make_comparison_frame(frame.copy())
    scores = video.compare_frames(left, right, 24)
    assert scores.layout_difference == pytest.approx(0)
    assert scores.changed_area == pytest.approx(0)
    assert scores.color_distance == pytest.approx(0)


def test_invalid_thresholds_are_rejected() -> None:
    """Invalid comparison settings must fail instead of producing bad output."""
    with pytest.raises(ValueError, match="between 0 and 1"):
        video.validate_thresholds(video.Thresholds(layout=1.1))


def test_process_video_writes_color_keyframes_and_manifest(tmp_path: Path) -> None:
    """The complete pipeline must save distinct color states and describe them."""
    source = tmp_path / "workflow.avi"
    output = tmp_path / "run"
    make_test_video(source)

    manifest_path = video.process_video(
        source,
        output,
        interval_seconds=0.25,
        comparison_width=160,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["source_video_path"] == str(source.resolve())
    assert manifest["candidate_frame_count"] == 6
    assert manifest["selected_frame_count"] >= 3
    assert manifest["frames"][0]["reason"] == ["first-frame"]
    assert "final-frame" in manifest["frames"][-1]["reason"]

    saved = cv2.imread(manifest["frames"][-1]["path"], cv2.IMREAD_COLOR)
    assert saved is not None
    assert saved.ndim == 3 and saved.shape[2] == 3
    assert not np.array_equal(saved[:, :, 0], saved[:, :, 1])


@pytest.mark.parametrize("frame_count", [1, 2, 3, 4, 5])
def test_contact_sheets_preserve_frame_order_and_originals(
    tmp_path: Path, frame_count: int
) -> None:
    """Sheets must map ordered tiles to unchanged full-resolution frames."""
    colors = [
        (20, 40, 60),
        (40, 60, 80),
        (60, 80, 100),
        (80, 100, 120),
        (100, 120, 140),
    ]
    frames = [
        make_selected_frame(index, colors[index - 1])
        for index in range(1, frame_count + 1)
    ]
    output = tmp_path / f"run-{frame_count}"
    output.mkdir()

    manifest_path = video.write_artifacts(
        tmp_path / "source.avi",
        output,
        video.VideoMetadata(1.0, float(frame_count), frame_count, 160, 90),
        0.5,
        frame_count,
        video.Thresholds(),
        frames,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["schema_version"] == 2
    assert manifest["contact_sheet_count"] == (frame_count + 3) // 4
    assert manifest["contact_sheet_layout"]["reading_order"] == (
        "left-to-right, then top-to-bottom"
    )
    assert [
        index
        for sheet in manifest["contact_sheets"]
        for index in sheet["frame_indices"]
    ] == list(range(1, frame_count + 1))

    for sheet_entry in manifest["contact_sheets"]:
        sheet = cv2.imread(sheet_entry["path"], cv2.IMREAD_COLOR)
        assert sheet is not None
        sheet_frame_count = len(sheet_entry["frame_indices"])
        expected_rows = (sheet_frame_count + 1) // 2
        expected_columns = min(2, sheet_frame_count)
        assert sheet.shape[:2] == (
            expected_rows * video.CONTACT_TILE_HEIGHT,
            expected_columns * video.CONTACT_TILE_WIDTH,
        )

        for tile_index, frame_index in enumerate(sheet_entry["frame_indices"]):
            row, column = divmod(tile_index, 2)
            sample_y = (
                row * video.CONTACT_TILE_HEIGHT
                + video.CONTACT_LABEL_HEIGHT
                + video.CONTACT_IMAGE_HEIGHT // 2
            )
            sample_x = column * video.CONTACT_TILE_WIDTH + 480
            assert tuple(sheet[sample_y, sample_x]) == colors[frame_index - 1]

    for frame_index, manifest_frame in enumerate(manifest["frames"], start=1):
        original = cv2.imread(manifest_frame["path"], cv2.IMREAD_COLOR)
        assert original is not None
        assert original.shape[:2] == (90, 160)
        assert tuple(original[45, 80]) == colors[frame_index - 1]


def test_contact_sheet_renders_frame_number_and_timestamp() -> None:
    """Every tile must carry a visible chronological label."""
    frame = make_selected_frame(7, (20, 40, 60))
    frame.timestamp_seconds = 65.25
    assert video.contact_sheet_label(7, frame.timestamp_seconds) == (
        "Frame 000007 | 00:01:05.250"
    )

    sheet = video.render_contact_sheet([(7, frame)])
    label_area = sheet[: video.CONTACT_LABEL_HEIGHT]
    assert np.any(np.all(label_area >= 240, axis=2))


def test_nonempty_output_directory_is_rejected(tmp_path: Path) -> None:
    """Processing must never overwrite files already present in its destination."""
    source = tmp_path / "workflow.avi"
    output = tmp_path / "run"
    make_test_video(source)
    output.mkdir()
    (output / "existing.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(FileExistsError):
        video.process_video(source, output)

    assert (output / "existing.txt").read_text(encoding="utf-8") == "keep"


def test_processing_failure_removes_all_partial_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed caller-owned run must not leave frames, sheets, or a manifest."""
    source = tmp_path / "workflow.avi"
    output = tmp_path / "run"
    make_test_video(source)
    output.mkdir()

    def fail_after_creating_artifacts(*args, **kwargs):
        artifact_dir = args[1]
        (artifact_dir / "frames").mkdir()
        (artifact_dir / "contact-sheets").mkdir()
        (artifact_dir / "manifest.json").write_text("{}", encoding="utf-8")
        raise RuntimeError("simulated artifact failure")

    monkeypatch.setattr(video, "write_artifacts", fail_after_creating_artifacts)

    with pytest.raises(RuntimeError, match="simulated artifact failure"):
        video.process_video(source, output, interval_seconds=0.25)

    assert output.is_dir()
    assert not (output / "frames").exists()
    assert not (output / "contact-sheets").exists()
    assert not (output / "manifest.json").exists()


def test_cli_prints_manifest_path(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """A host agent must receive the manifest location from the CLI output."""
    source = tmp_path / "workflow.avi"
    output = tmp_path / "cli-run"
    make_test_video(source)

    exit_code = video.main(
        [
            str(source),
            "--output-dir",
            str(output),
            "--interval",
            "0.25",
        ]
    )

    assert exit_code == 0
    assert Path(capsys.readouterr().out.strip()) == output / "manifest.json"
