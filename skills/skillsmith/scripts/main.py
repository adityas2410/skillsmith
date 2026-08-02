
"""Extract meaningful, full-color UI keyframes from a screen recording."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import cv2
import numpy as np
from skimage.metrics import structural_similarity


CONTACT_SHEET_COLUMNS = 2
CONTACT_SHEET_MAX_FRAMES = 4
CONTACT_TILE_WIDTH = 960
CONTACT_IMAGE_HEIGHT = 540
CONTACT_LABEL_HEIGHT = 56
CONTACT_TILE_HEIGHT = CONTACT_LABEL_HEIGHT + CONTACT_IMAGE_HEIGHT


@dataclass(frozen=True)
class VideoMetadata:
    fps: float
    duration_seconds: float
    frame_count: int
    width: int
    height: int


@dataclass(frozen=True)
class DiffScores:
    layout_difference: float
    changed_area: float
    color_distance: float


@dataclass
class ComparisonFrame:
    rgb: np.ndarray
    gray: np.ndarray
    rgb_histograms: tuple[np.ndarray, np.ndarray, np.ndarray]
    hsv_histogram: np.ndarray


@dataclass
class SelectedFrame:
    source_frame_index: int
    timestamp_seconds: float
    png_bytes: bytes
    comparison: ComparisonFrame
    reasons: list[str]
    scores: DiffScores | None
    is_first: bool = False
    is_final: bool = False


@dataclass(frozen=True)
class Thresholds:
    layout: float = 0.08
    changed_area: float = 0.03
    color: float = 0.16
    pixel: int = 24
    max_gap_seconds: float = 10.0
    duplicate_layout: float = 0.012
    duplicate_changed_area: float = 0.006
    duplicate_color: float = 0.035


def read_metadata(capture: cv2.VideoCapture, source: Path) -> VideoMetadata:
    """Read basic video properties and reject files with unusable metadata."""
    fps = float(capture.get(cv2.CAP_PROP_FPS))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if not math.isfinite(fps) or fps <= 0:
        raise ValueError(f"Video reports an invalid frame rate: {fps!r}")
    if frame_count <= 0 or width <= 0 or height <= 0:
        raise ValueError(f"Could not read video metadata from {source}")

    return VideoMetadata(
        fps=fps,
        duration_seconds=frame_count / fps,
        frame_count=frame_count,
        width=width,
        height=height,
    )


def candidate_frame_indices(
    metadata: VideoMetadata, interval_seconds: float
) -> list[int]:
    """Choose which video-frame numbers to inspect at the requested interval."""
    if interval_seconds <= 0:
        raise ValueError("Candidate interval must be greater than zero")

    step = max(1, int(round(interval_seconds * metadata.fps)))
    indices = list(range(0, metadata.frame_count, step))
    final_index = metadata.frame_count - 1
    if not indices or indices[-1] != final_index:
        indices.append(final_index)
    return indices


def iter_candidate_frames(
    capture: cv2.VideoCapture, indices: Iterable[int]
) -> Iterable[tuple[int, np.ndarray]]:
    """Decode the video in order and yield only frames selected as candidates."""
    targets = iter(indices)
    target = next(targets, None)
    frame_index = 0

    while target is not None:
        ok, frame = capture.read()
        if not ok:
            break
        if frame_index == target:
            yield frame_index, frame
            target = next(targets, None)
        frame_index += 1

    if target is not None:
        raise ValueError(
            f"Video decoding ended before candidate frame {target} could be read"
        )


def make_comparison_frame(
    bgr: np.ndarray, comparison_width: int = 640
) -> ComparisonFrame:
    """Build smaller grayscale and color copies used only for comparisons."""
    height, width = bgr.shape[:2]
    scale = min(1.0, comparison_width / width)
    resized = cv2.resize(
        bgr,
        (max(1, round(width * scale)), max(1, round(height * scale))),
        interpolation=cv2.INTER_AREA,
    )
    rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)

    rgb_histograms = tuple(
        cv2.normalize(
            cv2.calcHist([rgb], [channel], None, [64], [0, 256]),
            None,
            alpha=1,
            norm_type=cv2.NORM_L1,
        )
        for channel in range(3)
    )
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    hsv_histogram = cv2.normalize(
        cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256]),
        None,
        alpha=1,
        norm_type=cv2.NORM_L1,
    )
    return ComparisonFrame(rgb, gray, rgb_histograms, hsv_histogram)


def compare_frames(
    previous: ComparisonFrame,
    current: ComparisonFrame,
    pixel_threshold: int,
) -> DiffScores:
    """Measure layout, changed-pixel area, and color differences between frames."""
    similarity = structural_similarity(
        previous.gray, current.gray, data_range=255
    )
    pixel_delta = cv2.absdiff(previous.rgb, current.rgb)
    changed_area = float(
        np.mean(np.max(pixel_delta, axis=2) >= pixel_threshold)
    )
    rgb_distances = [
        cv2.compareHist(left, right, cv2.HISTCMP_BHATTACHARYYA)
        for left, right in zip(
            previous.rgb_histograms, current.rgb_histograms, strict=True
        )
    ]
    hsv_distance = cv2.compareHist(
        previous.hsv_histogram,
        current.hsv_histogram,
        cv2.HISTCMP_BHATTACHARYYA,
    )
    color_distance = 0.5 * hsv_distance + 0.5 * float(np.mean(rgb_distances))
    return DiffScores(
        layout_difference=max(0.0, min(1.0, 1.0 - float(similarity))),
        changed_area=max(0.0, min(1.0, changed_area)),
        color_distance=max(0.0, min(1.0, float(color_distance))),
    )


def selection_reasons(
    scores: DiffScores,
    elapsed_seconds: float,
    thresholds: Thresholds,
) -> list[str]:
    """Explain which configured rules make a candidate worth saving."""
    reasons: list[str] = []
    if scores.layout_difference >= thresholds.layout:
        reasons.append("layout-change")
    if scores.changed_area >= thresholds.changed_area:
        reasons.append("changed-area")
    if scores.color_distance >= thresholds.color:
        reasons.append("color-state-change")
    if elapsed_seconds >= thresholds.max_gap_seconds:
        reasons.append("maximum-gap")
    return reasons


def validate_thresholds(thresholds: Thresholds) -> None:
    """Reject comparison thresholds outside their meaningful numeric ranges."""
    unit_interval_values = {
        "layout threshold": thresholds.layout,
        "changed-area threshold": thresholds.changed_area,
        "color threshold": thresholds.color,
        "duplicate layout threshold": thresholds.duplicate_layout,
        "duplicate changed-area threshold": thresholds.duplicate_changed_area,
        "duplicate color threshold": thresholds.duplicate_color,
    }
    for label, value in unit_interval_values.items():
        if not 0 <= value <= 1:
            raise ValueError(f"{label.capitalize()} must be between 0 and 1")
    if not 0 <= thresholds.pixel <= 255:
        raise ValueError("Pixel threshold must be between 0 and 255")
    if thresholds.max_gap_seconds <= 0:
        raise ValueError("Maximum gap must be greater than zero")


def encode_png(frame: np.ndarray) -> bytes:
    """Compress a full-resolution color frame into PNG bytes for later saving."""
    ok, encoded = cv2.imencode(".png", frame)
    if not ok:
        raise ValueError("OpenCV could not encode a selected frame as PNG")
    return encoded.tobytes()


def select_keyframes(
    capture: cv2.VideoCapture,
    metadata: VideoMetadata,
    indices: list[int],
    thresholds: Thresholds,
    comparison_width: int,
) -> list[SelectedFrame]:
    """Keep candidates that differ meaningfully from the last selected frame."""
    selected: list[SelectedFrame] = []
    final_index = metadata.frame_count - 1

    for frame_index, bgr in iter_candidate_frames(capture, indices):
        timestamp = frame_index / metadata.fps
        comparison = make_comparison_frame(bgr, comparison_width)
        is_first = frame_index == 0
        is_final = frame_index == final_index

        if not selected:
            reasons = ["first-frame"]
            if is_final:
                reasons.append("final-frame")
            scores = None
        else:
            scores = compare_frames(
                selected[-1].comparison, comparison, thresholds.pixel
            )
            reasons = selection_reasons(
                scores,
                timestamp - selected[-1].timestamp_seconds,
                thresholds,
            )
            if is_final:
                reasons.append("final-frame")

        if reasons:
            selected.append(
                SelectedFrame(
                    source_frame_index=frame_index,
                    timestamp_seconds=timestamp,
                    png_bytes=encode_png(bgr),
                    comparison=comparison,
                    reasons=reasons,
                    scores=scores,
                    is_first=is_first,
                    is_final=is_final,
                )
            )

    return selected


def is_near_duplicate(
    previous: SelectedFrame,
    current: SelectedFrame,
    thresholds: Thresholds,
) -> bool:
    """Return whether two selected frames are too visually similar to keep both."""
    scores = compare_frames(
        previous.comparison, current.comparison, thresholds.pixel
    )
    return (
        scores.layout_difference < thresholds.duplicate_layout
        and scores.changed_area < thresholds.duplicate_changed_area
        and scores.color_distance < thresholds.duplicate_color
    )


def remove_adjacent_duplicates(
    selected: list[SelectedFrame], thresholds: Thresholds
) -> list[SelectedFrame]:
    """Remove neighboring duplicates while preserving the video endpoints."""
    cleaned: list[SelectedFrame] = []
    for frame in selected:
        if not cleaned or not is_near_duplicate(cleaned[-1], frame, thresholds):
            cleaned.append(frame)
            continue

        # Preserve the required endpoints. Prefer the final frame over a duplicate
        # intermediate frame so the saved timeline still ends at the video boundary.
        if frame.is_final and not cleaned[-1].is_first:
            cleaned[-1] = frame
        elif frame.is_first or frame.is_final:
            cleaned.append(frame)

    for index, frame in enumerate(cleaned):
        frame.scores = (
            None
            if index == 0
            else compare_frames(
                cleaned[index - 1].comparison,
                frame.comparison,
                thresholds.pixel,
            )
        )
    return cleaned


def format_timestamp(seconds: float) -> str:
    """Format a video time as a filename-safe HH-MM-SS.mmm string."""
    milliseconds = int(round(seconds * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}-{minutes:02d}-{whole_seconds:02d}.{millis:03d}"


def format_display_timestamp(seconds: float) -> str:
    """Format a video time for a human-readable contact-sheet label."""
    return format_timestamp(seconds).replace("-", ":", 2)


def contact_sheet_label(frame_index: int, timestamp_seconds: float) -> str:
    """Return the visible label printed above a contact-sheet frame."""
    return (
        f"Frame {frame_index:06d} | "
        f"{format_display_timestamp(timestamp_seconds)}"
    )


def decode_selected_frame(frame: SelectedFrame) -> np.ndarray:
    """Decode a selected frame's saved PNG bytes for contact-sheet rendering."""
    decoded = cv2.imdecode(
        np.frombuffer(frame.png_bytes, dtype=np.uint8), cv2.IMREAD_COLOR
    )
    if decoded is None:
        raise ValueError("OpenCV could not decode a selected frame PNG")
    return decoded


def render_contact_sheet(
    indexed_frames: list[tuple[int, SelectedFrame]],
) -> np.ndarray:
    """Render up to four ordered frames in a labeled two-column grid."""
    if not 1 <= len(indexed_frames) <= CONTACT_SHEET_MAX_FRAMES:
        raise ValueError("A contact sheet requires between one and four frames")

    columns = min(CONTACT_SHEET_COLUMNS, len(indexed_frames))
    rows = math.ceil(len(indexed_frames) / CONTACT_SHEET_COLUMNS)
    sheet = np.full(
        (rows * CONTACT_TILE_HEIGHT, columns * CONTACT_TILE_WIDTH, 3),
        24,
        dtype=np.uint8,
    )

    for tile_index, (frame_index, frame) in enumerate(indexed_frames):
        row, column = divmod(tile_index, CONTACT_SHEET_COLUMNS)
        tile_left = column * CONTACT_TILE_WIDTH
        tile_top = row * CONTACT_TILE_HEIGHT
        image_top = tile_top + CONTACT_LABEL_HEIGHT

        decoded = decode_selected_frame(frame)
        height, width = decoded.shape[:2]
        scale = min(CONTACT_TILE_WIDTH / width, CONTACT_IMAGE_HEIGHT / height)
        resized_width = max(1, round(width * scale))
        resized_height = max(1, round(height * scale))
        interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
        resized = cv2.resize(
            decoded,
            (resized_width, resized_height),
            interpolation=interpolation,
        )

        frame_left = tile_left + (CONTACT_TILE_WIDTH - resized_width) // 2
        frame_top = image_top + (CONTACT_IMAGE_HEIGHT - resized_height) // 2
        sheet[
            frame_top : frame_top + resized_height,
            frame_left : frame_left + resized_width,
        ] = resized

        label = contact_sheet_label(frame_index, frame.timestamp_seconds)
        text_size, _ = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2
        )
        text_y = tile_top + (CONTACT_LABEL_HEIGHT + text_size[1]) // 2
        cv2.putText(
            sheet,
            label,
            (tile_left + 18, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
        cv2.rectangle(
            sheet,
            (tile_left, tile_top),
            (
                tile_left + CONTACT_TILE_WIDTH - 1,
                tile_top + CONTACT_TILE_HEIGHT - 1,
            ),
            (80, 80, 80),
            1,
        )

    return sheet


def prepare_output_directory(output_dir: Path | None) -> tuple[Path, bool]:
    """Create an empty run directory, using the system temp folder by default."""
    created_for_run = output_dir is None
    if output_dir is None:
        root = Path(tempfile.gettempdir()) / "skillsmith"
        root.mkdir(parents=True, exist_ok=True)
        output_dir = root / uuid.uuid4().hex

    output_dir = output_dir.expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_dir}")
    if not output_dir.exists():
        created_for_run = True
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir, created_for_run


def write_artifacts(
    source: Path,
    output_dir: Path,
    metadata: VideoMetadata,
    interval_seconds: float,
    candidate_count: int,
    thresholds: Thresholds,
    frames: list[SelectedFrame],
) -> Path:
    """Write final distinct PNGs and a manifest that lists them in time order."""
    frames_dir = output_dir / "frames"
    frames_dir.mkdir()
    contact_sheets_dir = output_dir / "contact-sheets"
    contact_sheets_dir.mkdir()
    manifest_frames: list[dict[str, object]] = []

    for output_index, frame in enumerate(frames, start=1):
        filename = (
            f"{output_index:06d}_{format_timestamp(frame.timestamp_seconds)}.png"
        )
        path = frames_dir / filename
        path.write_bytes(frame.png_bytes)
        manifest_frames.append(
            {
                "index": output_index,
                "source_frame_index": frame.source_frame_index,
                "timestamp_seconds": round(frame.timestamp_seconds, 6),
                "path": str(path),
                "reason": frame.reasons,
                "diff_scores": asdict(frame.scores) if frame.scores else None,
            }
        )

    manifest_contact_sheets: list[dict[str, object]] = []
    for offset in range(0, len(frames), CONTACT_SHEET_MAX_FRAMES):
        sheet_index = len(manifest_contact_sheets) + 1
        indexed_frames = [
            (frame_index, frames[frame_index - 1])
            for frame_index in range(
                offset + 1,
                min(offset + CONTACT_SHEET_MAX_FRAMES, len(frames)) + 1,
            )
        ]
        sheet_path = contact_sheets_dir / f"{sheet_index:06d}.png"
        sheet_path.write_bytes(encode_png(render_contact_sheet(indexed_frames)))
        manifest_contact_sheets.append(
            {
                "index": sheet_index,
                "path": str(sheet_path),
                "frame_indices": [index for index, _ in indexed_frames],
            }
        )

    manifest = {
        "schema_version": 2,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_video_path": str(source),
        "duration_seconds": round(metadata.duration_seconds, 6),
        "fps": round(metadata.fps, 6),
        "frame_count": metadata.frame_count,
        "width": metadata.width,
        "height": metadata.height,
        "candidate_interval_seconds": interval_seconds,
        "candidate_frame_count": candidate_count,
        "selected_frame_count": len(frames),
        "contact_sheet_count": len(manifest_contact_sheets),
        "contact_sheet_layout": {
            "columns": CONTACT_SHEET_COLUMNS,
            "max_frames_per_sheet": CONTACT_SHEET_MAX_FRAMES,
            "tile_width": CONTACT_TILE_WIDTH,
            "image_height": CONTACT_IMAGE_HEIGHT,
            "label_height": CONTACT_LABEL_HEIGHT,
            "reading_order": "left-to-right, then top-to-bottom",
        },
        "contact_sheets": manifest_contact_sheets,
        "comparison": {
            "color_saved": True,
            "thresholds": asdict(thresholds),
        },
        "frames": manifest_frames,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest_path


def process_video(
    source: Path,
    output_dir: Path | None = None,
    interval_seconds: float = 0.5,
    comparison_width: int = 640,
    thresholds: Thresholds | None = None,
) -> Path:
    """Run video decoding, selection, deduplication, and artifact generation."""
    source = source.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"Video does not exist: {source}")
    if comparison_width < 64:
        raise ValueError("Comparison width must be at least 64 pixels")

    output_dir, created_for_run = prepare_output_directory(output_dir)
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        if created_for_run:
            shutil.rmtree(output_dir, ignore_errors=True)
        raise ValueError(f"OpenCV could not open video: {source}")

    try:
        metadata = read_metadata(capture, source)
        indices = candidate_frame_indices(metadata, interval_seconds)
        active_thresholds = thresholds or Thresholds()
        validate_thresholds(active_thresholds)
        selected = select_keyframes(
            capture,
            metadata,
            indices,
            active_thresholds,
            comparison_width,
        )
        selected = remove_adjacent_duplicates(selected, active_thresholds)
        return write_artifacts(
            source,
            output_dir,
            metadata,
            interval_seconds,
            len(indices),
            active_thresholds,
            selected,
        )
    except Exception:
        if created_for_run:
            shutil.rmtree(output_dir, ignore_errors=True)
        else:
            shutil.rmtree(output_dir / "frames", ignore_errors=True)
            shutil.rmtree(output_dir / "contact-sheets", ignore_errors=True)
            (output_dir / "manifest.json").unlink(missing_ok=True)
        raise
    finally:
        capture.release()


def build_parser() -> argparse.ArgumentParser:
    """Define the command-line arguments accepted by the processing script."""
    parser = argparse.ArgumentParser(
        description=(
            "Extract an ordered set of meaningful, full-color UI keyframes "
            "and a JSON manifest from a screen recording."
        )
    )
    parser.add_argument("video", type=Path, help="Path to the source video")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Run artifact directory (defaults to the system temp directory)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=0.5,
        help="Candidate sampling interval in seconds (default: 0.5)",
    )
    parser.add_argument(
        "--comparison-width",
        type=int,
        default=640,
        help="Maximum width used for comparison-only images (default: 640)",
    )
    parser.add_argument("--layout-threshold", type=float, default=0.08)
    parser.add_argument("--changed-area-threshold", type=float, default=0.03)
    parser.add_argument("--color-threshold", type=float, default=0.16)
    parser.add_argument("--pixel-threshold", type=int, default=24)
    parser.add_argument("--max-gap", type=float, default=10.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the command-line program and print the generated manifest path."""
    args = build_parser().parse_args(argv)
    thresholds = Thresholds(
        layout=args.layout_threshold,
        changed_area=args.changed_area_threshold,
        color=args.color_threshold,
        pixel=args.pixel_threshold,
        max_gap_seconds=args.max_gap,
    )
    try:
        manifest_path = process_video(
            args.video,
            args.output_dir,
            args.interval,
            args.comparison_width,
            thresholds,
        )
    except (FileNotFoundError, FileExistsError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    print(manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
