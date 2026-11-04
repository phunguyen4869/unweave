"""First-run setup: FFmpeg and the separation engine, installed inside the app.

Replaces installer/bootstrap.ps1. Runs as a Library job (kind "setup") so its
progress streams over the same /api/state polling the .progress-view frontend
already uses for separation jobs — no new frontend plumbing.
"""

import importlib.util
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import tomllib
import zipfile
from pathlib import Path
from urllib.request import urlopen

from .processes import popen, stop as stop_process
from .tools import EXE, embedded_runtime, ensure_ffmpeg_on_path, ffmpeg_dir, packages_prefix, MISSING_FFMPEG

# pip prints "Downloading name (123.4 MB)" then, when a progress bar is available,
# lines like "12.3/123.4 MB 2.5 MB/s". Both feed the setup download-speed UI.
_PIP_DOWNLOAD_START = re.compile(
    r"^\s*Downloading\s+(\S+)\s+\(([\d.,]+)\s*(kB|KB|MB|GB|KiB|MiB|GiB)\)\s*$",
    re.IGNORECASE,
)
_PIP_DOWNLOAD_RATE = re.compile(
    r"([\d.,]+)\s*/\s*([\d.,]+)\s*(kB|KB|MB|GB|KiB|MiB|GiB)"
    r"\s+([\d.,]+)\s*(kB|KB|MB|GB|KiB|MiB|GiB)/s",
    re.IGNORECASE,
)
_SIZE_UNITS = {
    "b": 1, "kb": 1000, "kib": 1024,
    "mb": 1000 ** 2, "mib": 1024 ** 2,
    "gb": 1000 ** 3, "gib": 1024 ** 3,
}

# Mirrors installer/bootstrap.ps1: ffmpeg/ffprobe land next to the app folder
# (install root), where tools.py already looks for them. The Windows build is a
# .zip of .exe files; Linux gets the johnvansickle static build (a .tar.xz); macOS
# gets evermeet.cx release zips (Intel binaries — also run under Rosetta on Apple
# Silicon). Prefer a system/Homebrew ffmpeg on PATH when present (ffmpeg_ok).
FFMPEG_URL_WINDOWS = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
FFMPEG_URL_LINUX = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
FFMPEG_URL_DARWIN_FFMPEG = "https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip"
FFMPEG_URL_DARWIN_FFPROBE = "https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip"
FFMPEG_SIZE_MB = 100
SEPARATION_SIZE_MB = 1600
YOUTUBE_SIZE_MB = 15
RUNTIME_SIZE_MB = 50


def ffmpeg_url() -> str:
    """Primary FFmpeg archive URL for this platform (for logs / single-archive hosts)."""
    if sys.platform.startswith("linux"):
        return FFMPEG_URL_LINUX
    if sys.platform == "darwin":
        return FFMPEG_URL_DARWIN_FFMPEG
    return FFMPEG_URL_WINDOWS


def _ffmpeg_download_jobs() -> list[tuple[str, str]]:
    """(label, url) archives to fetch. Darwin ships ffmpeg and ffprobe as separate zips."""
    if sys.platform == "darwin":
        return [("ffmpeg", FFMPEG_URL_DARWIN_FFMPEG), ("ffprobe", FFMPEG_URL_DARWIN_FFPROBE)]
    if sys.platform.startswith("linux"):
        return [("ffmpeg", FFMPEG_URL_LINUX)]
    return [("ffmpeg", FFMPEG_URL_WINDOWS)]


def _host_arch_ok() -> bool:
    """The Linux static build is x86-64 only; arm64 Linux has no equivalent download.
    macOS uses evermeet Intel zips (Rosetta on Apple Silicon)."""
    if sys.platform.startswith("linux"):
        machine = platform.machine().lower()
        return machine in {"x86_64", "amd64"}
    return True


STAGE_ORDER = ("ffmpeg", "separation", "youtube")

# Progress budget: 0..90 is split across the stages being downloaded, the last
# 10 points are the verify/finalize stretch.
FINALIZE_BAND = 10


def _install_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _pyproject() -> Path:
    return _install_dir() / "pyproject.toml"


def runtime_ok() -> bool:
    """Stage 1: the embedded runtime ships with the installer; if we're running
    on it with pywebview importable, nothing to download."""
    return importlib.util.find_spec("webview") is not None


def ffmpeg_ok() -> bool:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True
    install = ffmpeg_dir()
    return (install / f"ffmpeg{EXE}").is_file() and (install / f"ffprobe{EXE}").is_file()


def _package_dir(name: str) -> Path | None:
    """Location of an installed package without importing it (importing torch can
    take seconds and may fail noisily on a half-written install)."""
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError):
        return None
    if spec is None:
        return None
    if spec.submodule_search_locations:
        return Path(next(iter(spec.submodule_search_locations)))
    return Path(spec.origin).parent if spec.origin else None


def _binary_ok(path: Path | None, minimum: int) -> bool:
    """A present-but-zeroed file is exactly what an interrupted pip install leaves
    behind. Checking the PE header (not just the size) catches those."""
    if path is None:
        return False
    try:
        if not path.is_file() or path.stat().st_size < minimum:
            return False
        with path.open("rb") as stream:
            head = stream.read(2)
    except OSError:
        return False
    if sys.platform == "win32":
        return head == b"MZ"
    # Non-Windows binaries (ELF/Mach-O) have no single fixed magic, but an
    # interrupted install leaves the file zero-filled — the case this check exists
    # to catch. `bool(head)` alone waved that through, since b"\0\0" is truthy.
    return bool(head) and head != b"\0" * len(head)


def torch_has_cuda() -> bool:
    """Whether the installed torch is a CUDA build, judged from its files.

    The UI server used to `import torch` just to ask torch.cuda.is_available(),
    which kept hundreds of MB resident in a process that never runs inference."""
    root = _package_dir("torch")
    if root is None:
        return False
    name = "torch_cuda.dll" if sys.platform == "win32" else "libtorch_cuda.so"
    return _binary_ok(root / "lib" / name, 1024 * 1024)


def torch_ok() -> bool:
    root = _package_dir("torch")
    if root is None:
        return False
    if sys.platform != "win32":
        return (root / "__init__.py").is_file()
    if not _binary_ok(root / "lib" / "torch_cpu.dll", 10 * 1024 * 1024):
        return False
    if not _binary_ok(root / "lib" / "torch_python.dll", 1024 * 1024):
        return False
    uv = root / "lib" / "uv.dll"
    if uv.exists() and not _binary_ok(uv, 10 * 1024):
        return False
    extension = next(root.glob("_C*.pyd"), None)
    return _binary_ok(extension, 1024)


def separation_ok() -> bool:
    # audio_separator can appear installed while torch is only half extracted;
    # the module check alone made that look like a healthy setup.
    return importlib.util.find_spec("audio_separator") is not None and torch_ok()


# Floor matching pyproject youtube extra. Older builds hit YouTube HTTP 400
# ("Precondition check failed") and surface as "download failed (exit 1)".
_YTDLP_MIN = (2025, 10, 14)


def youtube_ok() -> bool:
    if importlib.util.find_spec("yt_dlp") is None:
        return False
    try:
        import yt_dlp
        parts = tuple(int(p) for p in str(yt_dlp.version.__version__).split(".")[:3])
    except Exception:
        return True
    return len(parts) == 3 and parts >= _YTDLP_MIN


def probe_separation() -> str:
    """Actually import the engine once after install; a missing DLL only shows up
    at import time, not from a files-only check."""
    try:
        result = subprocess.run([sys.executable, "-c", "import torch, audio_separator"],
                                capture_output=True, text=True, errors="replace", timeout=180)
    except (OSError, subprocess.TimeoutExpired) as error:
        return str(error)
    if result.returncode == 0:
        return ""
    detail = (result.stderr or result.stdout).strip().splitlines()
    return detail[-1] if detail else f"exit {result.returncode}"


def stage_requirements(stage: str) -> list[str]:
    """Read pip requirements for a stage from pyproject.toml optional-dependencies,
    the source of truth for what gets installed."""
    extras = {
        "separation": ["separation", "guitars"],
        "youtube": ["youtube"],
    }[stage]
    try:
        data = tomllib.loads(_pyproject().read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Can't read {_pyproject()}: {error}") from error
    declared = data.get("project", {}).get("optional-dependencies", {})
    requirements = []
    for extra in extras:
        requirements.extend(declared.get(extra, []))
    if not requirements:
        raise RuntimeError(f"No requirements declared for the '{stage}' extra in pyproject.toml")
    return requirements


def _log(library, message: str):
    with library.lock:
        library.logs.append(message[-2000:])


def _bytes_from_size(value: str, unit: str) -> int:
    """Convert a pip size token like ('12.3', 'MB') into an integer byte count."""
    number = float(value.replace(",", ""))
    return int(number * _SIZE_UNITS[unit.lower()])


def _tick(library, phase: str, stage: str | None, progress: int, *,
          received: int | None = None, total: int | None = None,
          speed: float | None = None, clear_download: bool = False,
          step_eta: float | None = None):
    """Push phase/progress, and optionally live download bytes + bytes/sec.

    ``clear_download`` drops the download_* fields (and step ETA) when leaving a
    transfer — prepare/install/finalize call it so the UI does not keep a stale
    MB/s from the previous stage.
    """
    with library.lock:
        job = library.job
        if job is None or job.get("status") not in {"running", "cancelling"}:
            return
        job["phase"] = phase
        job["stage"] = stage
        job["progress"] = max(0, min(100, int(progress)))
        if clear_download:
            for key in ("download_received", "download_total", "download_speed",
                        "install_started_at", "install_packages"):
                job.pop(key, None)
            job["step_eta"] = None
            job["step_eta_at"] = None
            return
        if received is not None:
            job["download_received"] = int(received)
        if total is not None:
            job["download_total"] = int(total)
        if speed is not None and speed > 0:
            job["download_speed"] = float(speed)
        if total and received is not None and total > 0:
            job["step_progress"] = max(0, min(100, int(100 * received / total)))
        if step_eta is not None:
            job["step_eta"] = max(0.0, float(step_eta))
            job["step_eta_at"] = time.time()


def _ensure_pip(library) -> None:
    """pip isn't guaranteed inside a stripped embedded Python; ensurepip ships
    with Python and works offline from its bundled wheel."""
    if importlib.util.find_spec("pip") is not None:
        return
    _log(library, "Installing pip into the embedded runtime…")
    command = [sys.executable, "-m", "ensurepip", "--upgrade"]
    process = popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               text=True, errors="replace")
    with library.lock:
        library.process = process
    try:
        for line in process.stdout:
            if _cancelling(library):
                stop_process(process)
                raise RuntimeError("Setup cancelled.")
            line = line.rstrip("\r\n")
            if line:
                _log(library, line)
    finally:
        if process.poll() is None:
            stop_process(process, force=True)
    code = process.wait()
    if code != 0:
        raise RuntimeError(f"ensurepip failed (exit {code}).")


def _cancelling(library) -> bool:
    with library.lock:
        return library.job is not None and library.job["status"] == "cancelling"


def _extract_ffmpeg_zip(archive: Path, install: Path) -> None:
    """Windows: the gyan.dev build nests the binaries under <root>/bin/."""
    with zipfile.ZipFile(archive) as zip_file:
        names = zip_file.namelist()
        ffmpeg_name = next((n for n in names if n.lower().endswith("/bin/ffmpeg.exe")), None)
        ffprobe_name = next((n for n in names if n.lower().endswith("/bin/ffprobe.exe")), None)
        if not ffmpeg_name or not ffprobe_name:
            raise RuntimeError("FFmpeg archive is missing ffmpeg.exe/ffprobe.exe.")
        with zip_file.open(ffmpeg_name) as source, (install / "ffmpeg.exe").open("wb") as target:
            shutil.copyfileobj(source, target)
        with zip_file.open(ffprobe_name) as source, (install / "ffprobe.exe").open("wb") as target:
            shutil.copyfileobj(source, target)


def _extract_darwin_binary_zip(archive: Path, install: Path, binary: str) -> None:
    """evermeet.cx zips ship a single Mach-O named ffmpeg or ffprobe at the root."""
    with zipfile.ZipFile(archive) as zip_file:
        names = [n for n in zip_file.namelist() if not n.endswith("/")]
        match = next((n for n in names if Path(n).name == binary), None)
        if match is None:
            match = next((n for n in names if Path(n).name.startswith(binary)), None)
        if match is None:
            raise RuntimeError(f"FFmpeg archive is missing {binary}.")
        target = install / binary
        with zip_file.open(match) as source, target.open("wb") as stream:
            shutil.copyfileobj(source, stream)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _extract_ffmpeg_tar(archive: Path, install: Path) -> None:
    """Linux: the static build keeps ffmpeg/ffprobe at the archive root and the
    binaries need the executable bit set explicitly — a plain extract() drops it,
    which shows up later as a bare PermissionError from subprocess."""
    wanted = {"ffmpeg", "ffprobe"}
    found: set[str] = set()
    with tarfile.open(archive, mode="r:xz") as tar_file:
        for member in tar_file.getmembers():
            name = Path(member.name).name
            if name not in wanted or not member.isfile():
                continue
            source = tar_file.extractfile(member)
            if source is None:
                continue
            target = install / name
            with source, target.open("wb") as stream:
                shutil.copyfileobj(source, stream)
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            found.add(name)
    if found != wanted:
        missing = ", ".join(sorted(wanted - found)) or "ffmpeg/ffprobe"
        raise RuntimeError(f"FFmpeg archive is missing {missing}.")


def _download_archive(library, url: str, archive: Path, start_progress: int, band: int,
                      *, progress_offset: float = 0.0, progress_span: float = 1.0) -> None:
    """Fetch one archive into `archive`, reporting progress into the setup job."""
    # Cap runaway downloads (a misbehaving proxy once filled a disk with 16 GB
    # "ffmpeg.zip" files). Abort past Content-Length, or 500 MB when unknown.
    try:
        with urlopen(url, timeout=60) as response, archive.open("wb") as stream:
            length = response.headers.get("Content-Length")
            expected = int(length) if length is not None else None
            max_bytes = expected if expected is not None else 500 * 1024 * 1024
            received = 0
            started = time.monotonic()
            last_report = 0.0
            while True:
                if _cancelling(library):
                    raise RuntimeError("Setup cancelled.")
                block = response.read(1024 * 1024)
                if not block:
                    break
                stream.write(block)
                received += len(block)
                if received > max_bytes:
                    raise RuntimeError("FFmpeg download was larger than expected")
                now = time.monotonic()
                elapsed = now - started
                # Throttle UI ticks; average speed from the whole transfer so far
                # so the number stays stable instead of bouncing on every chunk.
                if elapsed >= 0.25 and (now - last_report) >= 0.25:
                    last_report = now
                    speed = received / elapsed
                    eta = ((expected - received) / speed) if expected and speed > 0 else None
                    if expected:
                        fraction = progress_offset + progress_span * (received / expected)
                        pct = start_progress + int(fraction * band)
                        _tick(library, "download", "ffmpeg",
                              start_progress + min(band, pct - start_progress),
                              received=received, total=expected, speed=speed,
                              step_eta=eta)
                    else:
                        _tick(library, "download", "ffmpeg", start_progress,
                              received=received, speed=speed)
                elif expected is None and received % (32 * 1024 * 1024) == 0:
                    _log(library, f"Downloaded {received // (1024 * 1024)} MiB…")
            if expected is not None and received != expected:
                raise RuntimeError("Incomplete FFmpeg download. Retry setup.")
            if received:
                elapsed = max(time.monotonic() - started, 1e-6)
                fraction = progress_offset + progress_span
                _tick(library, "download", "ffmpeg",
                      start_progress + int(fraction * band),
                      received=received, total=expected or received,
                      speed=received / elapsed, step_eta=0)
    except Exception:
        try:
            archive.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _install_ffmpeg(library, start_progress: int, band: int) -> int:
    """Download FFmpeg and place ffmpeg + ffprobe next to the app folder. Returns
    the progress reached."""
    if not _host_arch_ok():
        raise RuntimeError("Automatic FFmpeg setup is only available for x86-64 on Linux. "
                           "Install FFmpeg with your package manager and reopen the app.")
    jobs = _ffmpeg_download_jobs()
    _tick(library, "download", "ffmpeg", start_progress, clear_download=True)
    _log(library, f"Downloading FFmpeg from {jobs[0][1]}…")
    with tempfile.TemporaryDirectory(prefix="unweave-ffmpeg-") as temporary:
        work = Path(temporary)
        install = ffmpeg_dir()
        install.mkdir(parents=True, exist_ok=True)
        span = 1.0 / len(jobs)
        archives: list[tuple[str, Path]] = []
        for index, (label, url) in enumerate(jobs):
            if len(jobs) > 1:
                _log(library, f"Downloading {label}…")
            if sys.platform.startswith("linux"):
                archive = work / "ffmpeg.tar.xz"
            else:
                archive = work / f"{label}.zip"
            _download_archive(library, url, archive, start_progress, band,
                              progress_offset=index * span, progress_span=span)
            archives.append((label, archive))
        if sys.platform.startswith("linux"):
            _extract_ffmpeg_tar(archives[0][1], install)
        elif sys.platform == "darwin":
            for label, archive in archives:
                _extract_darwin_binary_zip(archive, install, label)
        else:
            _extract_ffmpeg_zip(archives[0][1], install)
    if not ensure_ffmpeg_on_path():
        raise RuntimeError("FFmpeg was installed but could not be added to PATH.")
    _log(library, "FFmpeg installed.")
    _tick(library, "install", "ffmpeg", start_progress + band, clear_download=True)
    return start_progress + band


def _pip_progress_from_line(line: str) -> dict | None:
    """Pull received/total/speed out of a pip download progress line, if any."""
    match = _PIP_DOWNLOAD_RATE.search(line)
    if not match:
        return None
    received = _bytes_from_size(match.group(1), match.group(3))
    total = _bytes_from_size(match.group(2), match.group(3))
    speed = float(_bytes_from_size(match.group(4), match.group(5)))
    return {"received": received, "total": total, "speed": speed}


# pip prints nothing while it unpacks wheels after "Installing collected packages",
# which takes minutes for torch on a slow disk. Ease the bar through this share of
# the stage band meanwhile, halving the remaining gap every INSTALL_CREEP_HALF_LIFE_S.
INSTALL_CREEP = (0.65, 0.95)
INSTALL_CREEP_HALF_LIFE_S = 60.0


def _creep_install(library, stage: str, start_progress: int, band: int,
                   started: float, stop: threading.Event) -> None:
    low, high = INSTALL_CREEP
    while not stop.wait(1.0):
        elapsed = time.time() - started
        fraction = high - (high - low) * 0.5 ** (elapsed / INSTALL_CREEP_HALF_LIFE_S)
        _tick(library, "install", stage, start_progress + int(band * fraction))


def _pip_install(library, requirements: list[str], stage: str, start_progress: int, band: int,
                 *, force=False) -> int:
    """pip-install a requirement list, streaming progress through the job."""
    _tick(library, "install", stage, start_progress, clear_download=True)
    quoted = " ".join(requirements)
    attempts = [["--force-reinstall"]] if force else [[]]
    if force:
        # A killed pip can leave dist-info/RECORD all zeroes; pip then cannot
        # parse it to uninstall. Installing over it still restores every file.
        attempts.append(["--ignore-installed"])
    for attempt, options in enumerate(attempts):
        if attempt:
            _log(library, "Damaged package metadata prevented uninstall; installing over it…")
        _log(library, f"pip install{' ' + ' '.join(options) if options else ''} {quoted}")
        # The embedded runtime sits in read-only Program Files, where pip would quietly
        # fall back to the shared per-user site (%APPDATA%\Python) that uninstall never
        # cleans and other Pythons also read. Install into the app's own folder instead.
        target = ["--prefix", str(packages_prefix()), "--no-warn-script-location"] if embedded_runtime() else []
        # Force a progress bar so large wheels (torch) expose MB/s even when stdout
        # is a pipe rather than a TTY — the UI reads those rate lines below.
        command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                   "--progress-bar", "on", *target, *options, *requirements]
        process = popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, errors="replace")
        with library.lock:
            library.process = process
        milestones = {"Collecting": 0.25, "Installing collected packages": 0.65,
                      "Successfully installed": 1.0}
        hit = {name: False for name in milestones}
        output = []
        file_total = None
        creep_stop = threading.Event()
        creep = None

        def stop_creep():
            # Join so a last creep tick cannot land after (and undo) the final one.
            creep_stop.set()
            if creep is not None:
                creep.join()

        try:
            for raw in process.stdout:
                if _cancelling(library):
                    stop_process(process)
                    raise RuntimeError("Setup cancelled.")
                # Progress bars rewrite the same line with \\r; split so each update
                # can refresh download_speed without waiting for a newline.
                for line in raw.replace("\r", "\n").split("\n"):
                    line = line.strip()
                    if not line:
                        continue
                    start = _PIP_DOWNLOAD_START.match(line)
                    if start:
                        file_total = _bytes_from_size(start.group(2), start.group(3))
                        output.append(line)
                        _log(library, line)
                        _tick(library, "download", stage,
                              start_progress + int(band * 0.25),
                              received=0, total=file_total)
                        continue
                    rate = _pip_progress_from_line(line)
                    if rate:
                        # Rate lines rewrite many times per second — update the
                        # job, but keep them out of the transcript.
                        total = rate["total"] or file_total
                        eta = ((total - rate["received"]) / rate["speed"]
                               if total and rate["speed"] > 0 else None)
                        _tick(library, "download", stage,
                              start_progress + int(band * 0.25),
                              received=rate["received"], total=total,
                              speed=rate["speed"], step_eta=eta)
                        continue
                    output.append(line)
                    _log(library, line)
                    for name, fraction in milestones.items():
                        if not hit[name] and line.startswith(name):
                            hit[name] = True
                            if name == "Successfully installed":
                                stop_creep()
                            clear = name != "Collecting"
                            _tick(library, "install", stage,
                                  start_progress + int(band * fraction),
                                  clear_download=clear)
                            if name == "Installing collected packages":
                                started = time.time()
                                packages = [p for p in line.partition(":")[2].split(",") if p.strip()]
                                with library.lock:
                                    if library.job is not None:
                                        library.job["install_started_at"] = started
                                        library.job["install_packages"] = len(packages)
                                creep = threading.Thread(target=_creep_install, daemon=True,
                                                         args=(library, stage, start_progress, band,
                                                               started, creep_stop))
                                creep.start()
        finally:
            stop_creep()
            if process.poll() is None:
                stop_process(process, force=True)
        code = process.wait()
        if code == 0:
            importlib.invalidate_caches()  # let this process find the new packages
            break
        retry = any("field larger than field limit" in line or "UninstallPathSet" in line
                    for line in output)
        if retry and attempt + 1 < len(attempts):
            continue
        raise RuntimeError(f"pip install failed for {stage} (exit {code}). See the setup log.")
    _tick(library, "install", stage, start_progress + band, clear_download=True)
    return start_progress + band


def run_setup(library, stages: list[str], *, repair: bool = False) -> None:
    """Run the requested setup stages, one job, streaming progress as it goes.

    When ``repair`` is true, requested stages are reinstalled even if already present
    (FFmpeg downloaded again; pip stages with ``--force-reinstall``).
    """
    needed = [stage for stage in STAGE_ORDER if stage in stages]
    if repair:
        missing = list(needed)
    else:
        missing = [stage for stage in needed
                   if (stage == "ffmpeg" and not ffmpeg_ok())
                   or (stage == "separation" and not separation_ok())
                   or (stage == "youtube" and not youtube_ok())]
    if not missing:
        with library.lock:
            job = library.job
            if job:
                job.update(status="succeeded", progress=100, phase="done", stage=None)
        return

    band = (100 - FINALIZE_BAND) // max(1, len(missing))
    cursor = 0
    try:
        _tick(library, "prepare", None, 0, clear_download=True)
        _log(library, "Repairing installed components…" if repair else "Checking what's already installed…")

        if "ffmpeg" in missing and (repair or not ffmpeg_ok()):
            if repair and ffmpeg_ok():
                _log(library, "Re-downloading FFmpeg…")
            cursor = _install_ffmpeg(library, cursor, band)
            _tick(library, "install", "ffmpeg", cursor, clear_download=True)

        _ensure_pip(library)

        if "separation" in missing and (repair or not separation_ok()):
            requirements = stage_requirements("separation")
            # A partial package can still expose audio_separator; force pip to replace
            # zeroed/interrupted files rather than saying "already satisfied".
            force = repair or importlib.util.find_spec("audio_separator") is not None
            if force:
                _log(library, "Repairing the separation engine…" if repair
                     else "Repairing an incomplete separation engine install…")
            cursor = _pip_install(library, requirements, "separation", cursor, band, force=force)
            _tick(library, "install", "separation", cursor, clear_download=True)
            problem = probe_separation()
            if problem:
                raise RuntimeError(f"Separation engine could not be loaded after installation: {problem}")

        if "youtube" in missing and (repair or not youtube_ok()):
            requirements = stage_requirements("youtube")
            force = repair or importlib.util.find_spec("yt_dlp") is not None
            if force and repair:
                _log(library, "Repairing YouTube support…")
            cursor = _pip_install(library, requirements, "youtube", cursor, band, force=force)
            _tick(library, "install", "youtube", cursor, clear_download=True)

        # Finalize: make sure everything is actually usable now.
        _tick(library, "finalize", None, min(100, cursor + FINALIZE_BAND), clear_download=True)
        if not ensure_ffmpeg_on_path():
            raise RuntimeError(MISSING_FFMPEG)
        if "separation" in missing and not separation_ok():
            raise RuntimeError("Separation engine install did not take effect; restart the app and try again.")
        if "youtube" in missing and not youtube_ok():
            raise RuntimeError("YouTube support install did not take effect; restart the app and try again.")
        _tick(library, "finalize", None, 100, clear_download=True)

        with library.lock:
            job = library.job
            if job and job["status"] == "running":
                job.update(status="succeeded", progress=100, phase="done", stage=None)
                for key in ("download_received", "download_total", "download_speed"):
                    job.pop(key, None)
    except Exception as error:
        with library.lock:
            job = library.job
            if job and job["status"] != "cancelling":
                job.update(status="failed", error=str(error))
