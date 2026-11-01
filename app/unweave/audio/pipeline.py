"""File normalization and pretrained source separation."""

import contextlib
import importlib.util
import logging
import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

from .sources import youtube_audio
from .model_cache import create_separator
from .output_files import validate_outputs
from ..tools import MISSING_FFMPEG, ensure_ffmpeg_on_path, cpu_threads

DEFAULT_MODEL = "htdemucs_6s.yaml"
VOCAL_MODEL = "UVR_MDXNET_KARA_2.onnx"
MODEL_STEMS = {
    VOCAL_MODEL: ("vocals", "instrumental"),
    "htdemucs.yaml": ("vocals", "drums", "bass", "other"),
    DEFAULT_MODEL: ("vocals", "drums", "bass", "guitar", "piano", "other"),
}
STEM_CHOICES = ("vocals", "drums", "bass", "guitar", "piano", "other", "instrumental")
# Produced by the guitar split, not by a separation model.
LEAF_STEMS = ("lead", "rhythm")


def model_request(own, grouped, split_guitar):
    """The stems a model must produce for this plan; leaves come from the split."""
    if own is None and grouped is None:
        return None
    required = set(own or ()) | set(grouped or ())
    if required & set(LEAF_STEMS) and not split_guitar:
        raise ValueError("lead and rhythm need the guitar split; pass --split-guitar.")
    required -= set(LEAF_STEMS)
    if split_guitar:
        required.add("guitar")
    if not required:
        raise ValueError("Choose at least one stem.")
    return sorted(required)


def legacy_group(model, own, grouped):
    """`--stems other,drums` predates `--group`: keep folding the unselected in."""
    if grouped is not None or own is None or "other" not in own:
        return grouped
    return ("other", *[stem for stem in MODEL_STEMS.get(model, ()) if stem not in own])


def publish_names(model, own, grouped):
    """Exactly the files that reach the destination; group members are absent."""
    names = list(own) if own is not None else list(MODEL_STEMS.get(model, ()))
    if grouped:
        names.append("other")
    return tuple(dict.fromkeys(names))


def select_model(model: str | None, stems: list[str] | None) -> tuple[str, tuple[str, ...] | None]:
    requested = tuple(dict.fromkeys(stems)) if stems is not None else None
    if requested is not None:
        if not requested or set(requested) - set(STEM_CHOICES):
            raise ValueError("Choose stems from: " + ", ".join(STEM_CHOICES))
    if model is None:
        # One 6-stem model for every multi-stem plan. The 4-stem fallback used to
        # swallow guitar and piano *inside* `other`, so identical ticks produced
        # different audio depending on which stems happened to be picked next to
        # them. 6-stem is a superset, so a plan can always fold what it does not
        # keep and discard the rest after inference.
        # The karaoke pair is the one exception: `instrumental` only exists in MDX.
        karaoke = set(MODEL_STEMS[VOCAL_MODEL])
        model = VOCAL_MODEL if requested is not None and set(requested) <= karaoke else DEFAULT_MODEL
    supported = MODEL_STEMS.get(model)
    if requested is not None:
        if supported is None:
            raise ValueError("--stems requires a known model: " + ", ".join(MODEL_STEMS))
        required = set(requested)
        missing = required - set(supported)
        if missing:
            raise ValueError(f"{model} cannot output {', '.join(sorted(missing))}; "
                             f"supported stems: {', '.join(supported)}")
    return model, requested if requested is not None else supported


def mix_stems(sources: list[Path], destination: Path) -> None:
    """amix `sources` into `destination` as 24-bit FLAC.

    Group members exist only inside this file: callers publish the result and
    never the members, which is how a merged stem disappears from disk.
    """
    missing = [str(source) for source in sources if not source.is_file()]
    if missing:
        raise RuntimeError("Cannot build Other; missing stems: " + ", ".join(missing))
    if len(sources) == 1:
        _flac_copy(sources[0], destination)
        return
    # Float WAV preserves sums above full scale without clipping or changing gain.
    # Write separately because FFmpeg cannot overwrite an input it is reading.
    with tempfile.TemporaryDirectory(prefix="other-mix-", dir=destination.parent) as temporary:
        mixed = Path(temporary) / "other.wav"
        inputs = [argument for source in sources for argument in ("-i", str(source))]
        subprocess.run([
            "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", *inputs,
            "-filter_complex", f"amix=inputs={len(sources)}:duration=longest:normalize=0",
            "-c:a", "pcm_f32le", str(mixed),
        ], check=True, stdout=sys.stderr)
        _flac_copy(mixed, destination)


def _flac_copy(source: Path, destination: Path) -> None:
    """Transcode to 24-bit FLAC via a sibling file so `source` may be replaced."""
    temporary = destination.with_name(destination.stem + ".tmp.flac")
    # FLAC has no float format; 24-bit keeps the float mix's precision at roughly
    # half the size of WAV.
    subprocess.run([
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-c:a", "flac", "-sample_fmt", "s32",
        "-bits_per_raw_sample", "24", str(temporary),
    ], check=True, stdout=sys.stderr)
    temporary.replace(destination)


def probe_duration(path: Path) -> float:
    try:
        result = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", str(path),
        ], capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        raise ValueError(MISSING_FFMPEG) from None
    except subprocess.TimeoutExpired:
        raise ValueError(f"Could not read the duration of {Path(path).name}.") from None
    if result.returncode:
        raise ValueError(f"Could not read the duration of {Path(path).name}.")
    try:
        duration = float(result.stdout.strip())
    except ValueError:
        raise ValueError(f"Could not read the duration of {Path(path).name}.") from None
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Could not read the duration of {Path(path).name}.")
    return duration


def parse_trim(trim, duration: float, minimum: float = 1.0):
    if trim is None:
        return None
    if isinstance(trim, dict):
        start, end = trim.get("start"), trim.get("end")
    elif isinstance(trim, (list, tuple)) and len(trim) == 2:
        start, end = trim
    else:
        raise ValueError("Choose a valid section.")
    if (not isinstance(start, (int, float)) or isinstance(start, bool)
            or not isinstance(end, (int, float)) or isinstance(end, bool)
            or not math.isfinite(start) or not math.isfinite(end)):
        raise ValueError("Choose a valid section.")
    start, end = float(start), float(end)
    if start < 0:
        raise ValueError("Choose a valid section.")
    if start >= end:
        raise ValueError("Choose a section longer than 1 second.")
    if end > duration + 0.05:
        raise ValueError(f"The section ends after the recording ({duration:.1f} s).")
    if end - start < minimum - 1e-9:
        if minimum == 1:
            raise ValueError("Choose a section longer than 1 second.")
        raise ValueError(f"Choose a section of at least {minimum:g} seconds.")
    return round(start, 3), round(end, 3)


def normalize(source: Path, destination: Path, trim=None) -> None:
    args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    duration = None
    if trim:
        start, end = trim
        duration = probe_duration(source)
        args += ["-ss", f"{start:.6f}"]
    args += ["-i", str(source)]
    filters = []
    if trim:
        start, end = trim
        args += ["-t", f"{end - start:.6f}"]
        if start > 0.0005:
            filters.append("afade=t=in:st=0:d=0.005")
        if end < duration - 0.0005:
            filters.append(f"afade=t=out:st={max(0.0, end - start - 0.005):.6f}:d=0.005")
    if filters:
        args += ["-af", ",".join(filters)]
    args += ["-map", "0:a:0", "-vn", "-ar", "44100", "-ac", "2",
             "-c:a", "pcm_s16le", str(destination)]
    subprocess.run(args, check=True, stdout=sys.stderr)


def output_directory(source: str, output: Path | None, youtube: bool = False) -> Path:
    if output is not None:
        directory = output.expanduser().resolve()
    elif youtube:
        parent = Path("stems").resolve()
        parent.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="track-", dir=parent))
    else:
        source_path = Path(source).expanduser().absolute()
        directory = source_path.with_name(source_path.stem).resolve()
        if directory == source_path.resolve():
            raise ValueError("Cannot derive an output folder from an extensionless input; use --output.")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def require_runtime(youtube: bool) -> None:
    if not ensure_ffmpeg_on_path():
        raise RuntimeError(MISSING_FFMPEG)
    if importlib.util.find_spec("audio_separator") is None:
        raise RuntimeError('Install separation support: pip install -e ".[separation]"')
    if youtube and importlib.util.find_spec("yt_dlp") is None:
        raise RuntimeError('YouTube support is not installed. Install it from the YouTube tab in the app '
                           '(or, from a dev checkout: pip install -e ".[youtube]").')


def _run_demucs(model: str, normalized: Path, stage: Path, cache: Path) -> dict[str, Path]:
    print(f"Loading model {model}", file=sys.stderr, flush=True)
    # Upstream progress/prints must not corrupt the JSON result on stdout.
    with contextlib.redirect_stdout(sys.stderr):
        separator = create_separator(
            output_dir=str(stage), output_format="FLAC",
            model_file_dir=str(cache), log_level=logging.WARNING,
            mdx_params={"hop_length": 1024, "segment_size": 256,
                        "overlap": 0.25, "batch_size": 1, "enable_denoise": False},
            demucs_params={"segment_size": "Default", "shifts": 0,
                           "overlap": 0.25, "segments_enabled": True},
        )
        separator.load_model(model_filename=model)
        print(f"Separating with {model}; model outputs: "
              f"{', '.join(MODEL_STEMS.get(model, ())) or 'all'}", file=sys.stderr)
        names = {stem: stem for stem in MODEL_STEMS.get(model, ())}
        results = separator.separate(str(normalized), custom_output_names=names or None)
        del separator
    paths = [stage / Path(name).name for name in results]
    if len(paths) < 2 or any(not path.is_file() or path.stat().st_size <= 44 for path in paths):
        raise RuntimeError("Separator did not produce valid stem files.")
    return {path.stem: path for path in paths}


def _run_guitar_split(by_stem: dict[str, Path], stage: Path, cache: Path):
    from .guitar_split import split_guitar as split_into_leaves
    if "guitar" not in by_stem:
        raise RuntimeError("The plan splits the guitar but the model did not produce one.")
    print("Splitting guitar", file=sys.stderr, flush=True)
    # The stems are already trimmed to the chosen section, so no trim is passed on.
    return {path.stem: path for path in split_into_leaves(by_stem["guitar"], stage, cache)}


def _build_other(by_stem: dict[str, Path], grouped) -> Path | None:
    """Mix the group into other.flac. Members are inputs only and stay unpublished."""
    if not grouped:
        return None
    names = list(dict.fromkeys(grouped))
    missing = [name for name in names if name not in by_stem]
    if missing:
        raise RuntimeError("The plan folds stems this run did not produce: " + ", ".join(sorted(missing)))
    destination = by_stem.get("other") or by_stem[names[0]].with_name("other.flac")
    if names != ["other"]:
        mix_stems([by_stem[name] for name in names], destination)
    return destination


def _collect(by_stem: dict[str, Path], names, other: Path | None, folded=()) -> list[Path]:
    missing = [name for name in names if name not in by_stem]
    if missing:
        raise RuntimeError("Model did not produce requested stems: " + ", ".join(sorted(missing)))
    paths = [by_stem[name] for name in names]
    if other is not None and other not in paths:
        paths.append(other)
    # The model computes every stem it can; whatever the plan neither keeps nor
    # folds into other.flac is dropped here and never reaches the project folder.
    kept = {path.stem for path in paths} | set(folded)
    dropped = sorted(name for name in by_stem if name not in kept)
    if dropped:
        print("Dropping unrequested stems: " + ", ".join(dropped), file=sys.stderr, flush=True)
    return paths


def resolve_plan(model: str | None, own, grouped, split_guitar: bool):
    """Choose the model and expand the flags into `(model, own, grouped)`.

    An explicit `group` is honoured exactly: `other.flac` is the mix of what it
    lists, so an empty group writes no `other.flac` at all. Only `--group` without
    `--stems` ("keep everything that is not folded") needs `other` added to the
    group, because there `other` is the destination rather than one more member."""
    model = select_model(model, model_request(own, grouped, split_guitar))[0]
    grouped = legacy_group(model, own, grouped)
    if grouped is None:
        return model, own, grouped
    produced = MODEL_STEMS.get(model, ())
    if own is None:
        if "other" in produced and "other" not in grouped:
            grouped = (*grouped, "other")
        own = tuple(name for name in produced if name not in grouped)
    return model, own, grouped


def separate(source: str, output: Path | None = None, model: str | None = None,
             cache: Path = Path(".sound-razor/models"), youtube: bool = False,
             stems: list[str] | None = None, group: list[str] | None = None,
             split_guitar: bool = False, trim=None) -> list[Path]:
    """Separate `source`. `stems` get their own files; `group` is folded into
    other.flac and never written as a file of its own."""
    own = None if stems is None else tuple(dict.fromkeys(stems))
    grouped = None if group is None else tuple(dict.fromkeys(group))
    model, own, grouped = resolve_plan(model, own, grouped, split_guitar)
    names = publish_names(model, own, grouped)
    if not youtube and not Path(source).expanduser().is_file():
        raise ValueError(f"Audio file does not exist: {source}")
    output = output_directory(source, output, youtube)
    original = None if youtube else Path(source).expanduser().resolve()
    settings = output / "separation.json"
    validate_outputs(original, [output / f"{name}.flac" for name in names] + [settings])
    require_runtime(youtube)
    cache = cache.expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    import torch
    torch.set_num_threads(cpu_threads())

    with tempfile.TemporaryDirectory(prefix="unweave-") as temporary:
        work = Path(temporary)
        audio = youtube_audio(source, work) if youtube else Path(source).expanduser().resolve()
        saved_trim = parse_trim(trim, probe_duration(audio), 1.0) if trim is not None else None
        normalized = work / "input.wav"
        # Phase markers below are parsed by the UI for its progress display.
        print("Preparing audio", file=sys.stderr, flush=True)
        normalize(audio, normalized, saved_trim)

        # Create staging on the destination filesystem BEFORE inference so the
        # separator writes stems directly there, eliminating the redundant
        # temp-dir copy (one fewer full stem-set write per job).
        with tempfile.TemporaryDirectory(prefix=".stems-", dir=output) as staged:
            stage = Path(staged)
            by_stem = _run_demucs(model, normalized, stage, cache)
            split_settings = {}
            if split_guitar:
                by_stem.update(_run_guitar_split(by_stem, stage, cache))
                split_settings = _read_settings(stage / settings.name)
            # Printed only once every inference pass is done: the guitar split is a
            # second pass that can run for minutes, and this marker is what the UI
            # treats as "nearly finished". Announcing it before the split left the
            # progress bar pinned near 96% for the whole second pass.
            print("Writing stems", file=sys.stderr, flush=True)
            other = _build_other(by_stem, grouped)
            paths = _collect(by_stem, names, other, grouped or ())
            destinations = [output / path.name for path in paths]
            validate_outputs(original, destinations + [settings])
            settings_value = {**split_settings, "stems": list(names), "group": list(grouped or ())}
            if saved_trim is not None:
                settings_value["trim"] = {"start": saved_trim[0], "end": saved_trim[1]}
            (stage / settings.name).write_text(json.dumps(settings_value, indent=2) + "\n", encoding="utf-8")
            validate_outputs(original, destinations + [settings])
            for destination in destinations + [settings]:
                (stage / destination.name).replace(destination)
        return [path.resolve() for path in destinations]


def _read_settings(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def train(dataset: Path) -> None:
    raise NotImplementedError(
        "Fine-tuning is not implemented: the inference backend has no training API. "
        "Provide aligned mixtures and isolated reference stems, choose a trainable "
        "architecture, and hold out songs for evaluation. Mixed album tracks alone "
        "are not supervised training targets. See README.md."
    )
