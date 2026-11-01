"""On-demand formatted copies of canonical project stems."""

from collections import deque
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import tempfile

from ..projects import describe_project
from ..projects.store import atomic_json
from ..processes import popen
from ..tools import MISSING_FFMPEG, ensure_ffmpeg_on_path
from .output_files import validate_outputs
from .pipeline import probe_duration

FORMATS = {
    "flac": {"extension": ".flac", "args": ["-c:a", "flac", "-compression_level", "5"]},
    "mp3": {"extension": ".mp3", "args": ["-c:a", "libmp3lame", "-b:a", "320k"]},
    "opus": {"extension": ".opus", "args": ["-c:a", "libopus", "-b:a", "192k"]},
    "m4a": {"extension": ".m4a", "args": ["-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart"]},
    "wav16": {"extension": ".wav", "args": ["-c:a", "pcm_s16le"]},
    "aiff": {"extension": ".aiff", "args": ["-c:a", "pcm_s16be"]},
}
LIMITER = "alimiter=limit=0.891:level=0:latency=1"


def _metadata_args(info: dict, label: str) -> list[str]:
    values = {
        "title": f"{info.get('title', '')} — {label}" if info.get("title") else label,
        "artist": info.get("artist", ""),
        "album": info.get("album", ""),
        "date": info.get("year", ""),
    }
    args = ["-map_metadata", "-1"]
    for key, value in values.items():
        if value:
            args += ["-metadata", f"{key}={value}"]
    return args


def convert(source: Path, destination: Path, format_id: str, metadata: list[str],
            prevent_clipping: bool, duration: float, report=None, set_process=None) -> None:
    spec = FORMATS[format_id]
    args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source), *metadata]
    if prevent_clipping:
        args += ["-af", LIMITER]
    args += ["-progress", "pipe:1", "-nostats", *spec["args"], str(destination)]
    process = popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    if set_process:
        set_process(process)
    tail = deque(maxlen=12)
    try:
        for line in process.stdout:
            line = line.strip()
            if line.startswith(("out_time_us=", "out_time_ms=")):
                try:
                    micros = int(line.split("=", 1)[1])
                except ValueError:
                    continue
                if duration > 0 and report:
                    report(min(1.0, micros / 1_000_000 / duration))
            elif line and not line.startswith(("progress=", "bitrate=", "speed=", "fps=",
                                               "total_size=", "out_time=", "dup_frames=",
                                               "drop_frames=", "frame=")):
                tail.append(line)
    finally:
        code = process.wait()
        process.stdout.close()
        if set_process:
            set_process(None)
    if code:
        detail = tail[-1] if tail else "FFmpeg could not convert the file."
        raise RuntimeError(f"Export failed for {source.name} ({code}). {detail}")


def export_stems(project: Path, stems: list[str], formats: list[str],
                 prevent_clipping: bool, report=None, set_process=None) -> list[Path]:
    if not ensure_ffmpeg_on_path():
        raise RuntimeError(MISSING_FFMPEG)
    project = Path(project).resolve()
    info = describe_project(project)
    by_file = {item["file"]: item for item in info["stems"]}
    chosen = []
    for name in stems or []:
        if not isinstance(name, str) or name not in by_file:
            raise ValueError("Unknown stem to export.")
        if name not in chosen:
            chosen.append(name)
    if not chosen:
        raise ValueError("Choose at least one stem to export.")
    selected_formats = []
    for format_id in formats or []:
        if not isinstance(format_id, str) or format_id not in FORMATS:
            raise ValueError("Unknown export format.")
        if format_id not in selected_formats:
            selected_formats.append(format_id)
    if not selected_formats:
        raise ValueError("Choose at least one export format.")
    sources = project / "stems"
    if sources.is_symlink():
        raise ValueError("The stems folder must not be a symlink.")
    exports = project / "exports"
    if exports.is_symlink() or (exports.exists() and not exports.is_dir()):
        raise ValueError("The exports folder must be a real directory.")
    total = len(chosen) * len(selected_formats)
    completed = 0
    files = []
    durations = {}
    if report:
        report(0.0, total, "Preparing export")
    with tempfile.TemporaryDirectory(prefix=".exports-", dir=project) as temporary:
        stage = Path(temporary)
        for stem_name in chosen:
            item = by_file[stem_name]
            source = sources / stem_name
            if source.is_symlink() or not source.is_file():
                raise ValueError(f"Stem must be a regular file: {stem_name}")
            if stem_name not in durations:
                durations[stem_name] = probe_duration(source)
            label = item["name"]
            metadata = _metadata_args(info, label)
            for format_id in selected_formats:
                output_name = f"{Path(stem_name).stem}{FORMATS[format_id]['extension']}"
                destination = stage / output_name
                validate_outputs(source, [destination])
                index = completed

                def on_fraction(fraction, index=index, label=label, output_name=output_name):
                    if report:
                        report(index + fraction, total,
                               f"Exporting {output_name} ({index + 1}/{total})")

                convert(source, destination, format_id, metadata, bool(prevent_clipping),
                        durations[stem_name], on_fraction, set_process)
                if not destination.is_file() or destination.stat().st_size <= 0:
                    raise RuntimeError(f"FFmpeg did not produce {output_name}.")
                completed += 1
                if report:
                    report(completed, total, f"Exported {output_name} ({completed}/{total})")
                files.append({"stem": stem_name, "label": label, "output": output_name,
                              "offset": item.get("offset", 0.0)})
        exports.mkdir(parents=True, exist_ok=True)
        if exports.is_symlink() or not exports.is_dir():
            raise ValueError("The exports folder must be a real directory.")
        for item in files:
            destination = exports / item["output"]
            validate_outputs(None, [destination])
        for item in files:
            os.replace(stage / item["output"], exports / item["output"])
        manifest = {
            "exported_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "formats": selected_formats,
            "prevent_clipping": bool(prevent_clipping),
            "files": files,
        }
        atomic_json(exports / "manifest.json", manifest)
    return [exports / item["output"] for item in files]
