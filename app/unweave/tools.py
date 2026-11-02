"""Locate FFmpeg when it is not on PATH (e.g. the installer's copy, WinGet, Scoop)."""

import glob
import os
from pathlib import Path
import shutil
import sys

EXE = ".exe" if os.name == "nt" else ""


def embedded_runtime() -> bool:
    """True on the Windows installer's embeddable Python (it ships a python*._pth file).

    That copy lives in Program Files, which the app can't write to without admin
    rights, so whatever setup downloads goes to app_data_dir() instead.
    """
    return any(Path(sys.executable).resolve().parent.glob("python*._pth"))


APP_NAME = "Unweave"
LEGACY_APP_NAME = "SoundRazer Desktop"  # the app's name up to 1.2.2


def app_version() -> str:
    """The version in pyproject.toml, which sits next to unweave/ in a checkout's app/
    folder and at the install root (the installer copies the repo root's one there)."""
    import tomllib
    try:
        with open(Path(__file__).resolve().parents[1] / "pyproject.toml", "rb") as stream:
            return tomllib.load(stream)["project"]["version"]
    except (OSError, KeyError, ValueError):
        return ""


def _local_app_data() -> Path:
    """Windows per-user Local AppData (also used when migrating a mis-pathed Unix install)."""
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")


def app_data_dir() -> Path:
    """Per-user folder for config, models and setup downloads (ui_entrypoint.py uses it too)."""
    if sys.platform == "win32":
        return _local_app_data() / APP_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_NAME
    xdg = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "unweave"


def migrate_legacy_data_dir() -> None:
    """Carry a pre-rename install's data over (setup's ~1.6 GB of packages, models,
    settings) by renaming the folder, so nothing is downloaded again. The installer
    does the same before removing the old version; this covers anything it missed.

    On Linux/macOS also moves a mistaken ~/AppData/Local/Unweave (from when
    app_data_dir always used the Windows layout) into the platform-correct path."""
    current = app_data_dir()
    candidates = []
    if sys.platform == "win32":
        candidates.append(_local_app_data() / LEGACY_APP_NAME)
    else:
        candidates.append(_local_app_data() / APP_NAME)
        candidates.append(_local_app_data() / LEGACY_APP_NAME)
    for legacy in candidates:
        if legacy.resolve() == current.resolve():
            continue
        if legacy.is_dir() and not current.exists():
            try:
                current.parent.mkdir(parents=True, exist_ok=True)
                legacy.rename(current)
            except OSError:
                pass  # in use by an old copy still running; the next launch retries
            return


def packages_prefix() -> Path:
    """pip --prefix for setup's packages on the embedded runtime; prepare_embedded_runtime()
    puts its Lib/site-packages on sys.path."""
    return app_data_dir() / "packages"


def prepare_embedded_runtime() -> None:
    """Run at interpreter start on the embedded runtime (installer/unweave.pth): keep the
    shared per-user site-packages out and put setup's own package folder on sys.path."""
    import site
    user_site = site.getusersitepackages()
    if user_site in sys.path:
        sys.path.remove(user_site)
    site.ENABLE_USER_SITE = False
    migrate_legacy_data_dir()
    packages = packages_prefix() / "Lib" / "site-packages"
    packages.mkdir(parents=True, exist_ok=True)  # on sys.path now, so setup's installs import at once
    site.addsitedir(str(packages))


def ffmpeg_dir() -> Path:
    """Where setup unpacks FFmpeg: the app data folder on the embedded runtime, else the
    install root next to the app (a writable portable folder on Linux and in dev)."""
    return app_data_dir() / "ffmpeg" if embedded_runtime() else Path(__file__).resolve().parents[1]


def _candidates():
    here = Path(__file__).resolve()
    roots = [Path.cwd(), here.parents[1], ffmpeg_dir(), *Path(sys.executable).resolve().parents[:3]]
    for root in roots:
        yield root
        yield root / "ffmpeg" / "bin"
        yield root / "bin"
    if os.name == "nt":
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        yield local / "Microsoft" / "WinGet" / "Links"
        yield from map(Path, glob.glob(str(local / "Microsoft" / "WinGet" / "Packages" / "*FFmpeg*" / "**" / "bin"), recursive=True))
        yield Path(os.environ.get("USERPROFILE", "")) / "scoop" / "shims"
        yield Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "chocolatey" / "bin"
        yield Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "ffmpeg" / "bin"
        yield Path(r"C:\ffmpeg\bin")
    else:
        yield Path("/opt/homebrew/bin")
        yield Path("/usr/local/bin")


def ensure_ffmpeg_on_path() -> bool:
    """Prepend a folder holding ffmpeg and ffprobe to PATH (also for child processes)."""
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True
    for folder in _candidates():
        if (folder / f"ffmpeg{EXE}").is_file() and (folder / f"ffprobe{EXE}").is_file():
            os.environ["PATH"] = f"{folder}{os.pathsep}{os.environ.get('PATH', '')}"
            return True
    return False


MISSING_FFMPEG = ("FFmpeg was not found. Install it (for example: winget install Gyan.FFmpeg) "
                  "or put ffmpeg.exe and ffprobe.exe in the Unweave folder, then restart the app.")


def env_first(*names: str) -> str | None:
    """First non-empty env value among names. New UNWEAVE_* names win; legacy
    SOUND_RAZOR_* names remain as fallbacks after the package rename."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return None


# 44.1 kHz stereo 16-bit PCM. FLAC stems come in under this, so sizing jobs by it
# over-asks a little rather than running out mid-write.
PCM_BYTES_PER_SECOND = 44100 * 2 * 2
DISK_HEADROOM = 200 * 1024 * 1024


def _size_label(size: float) -> str:
    return f"{size / 1024 ** 3:.1f} GB" if size >= 1024 ** 3 else f"{max(1, round(size / 1024 ** 2))} MB"


def require_free_space(path: Path, needed: float) -> None:
    """Refuse a job up front when `path`'s drive cannot hold `needed` bytes.

    Without this a full disk surfaces mid-job as an FFmpeg or model error that
    never mentions space."""
    probe = Path(path)
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    try:
        free = shutil.disk_usage(probe).free
    except OSError:
        return
    if free < needed + DISK_HEADROOM:
        drive = probe.anchor or str(probe)
        raise ValueError(f"Not enough disk space on {drive}: this needs about "
                         f"{_size_label(needed + DISK_HEADROOM)} but only {_size_label(free)} is free. "
                         "Free up some space and try again.")


def total_ram_gb(default: float = 8.0) -> float:
    """Physical RAM in GiB; `default` when the platform cannot say.

    os.sysconf does not exist on Windows, which used to leave every Windows
    machine assuming 8 GiB."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 ** 3)
    except (AttributeError, OSError, ValueError):
        pass
    if sys.platform == "win32":
        import ctypes

        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("page_total", ctypes.c_ulonglong), ("page_avail", ctypes.c_ulonglong),
                        ("virtual_total", ctypes.c_ulonglong), ("virtual_avail", ctypes.c_ulonglong),
                        ("extended", ctypes.c_ulonglong)]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        try:
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.total / (1024 ** 3)
        except (AttributeError, OSError):
            pass
    return default


def cpu_threads() -> int:
    """Return inference thread count, leaving one core free for the server/UI.

    Override with UNWEAVE_THREADS (or legacy SOUND_RAZOR_THREADS). Falls back to 1
    if cpu_count() is unavailable.
    """
    override = env_first("UNWEAVE_THREADS", "SOUND_RAZOR_THREADS")
    if override:
        try:
            return max(1, int(override))
        except ValueError:
            pass
    count = os.cpu_count() or 1
    return max(1, count - 1)
