"""Leftover-file scanner and cleaner (spec 13).

Only known temp / staging / download leftovers are considered, and only when every
safety rule holds. Sizing never follows links; deleting re-validates each item.
"""

from __future__ import annotations

import fnmatch
import hashlib
import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .fsutil import dir_bytes, is_link_like
from .tools import app_data_dir

AGE_HOURS = 24
SILENT_BYTES = 50 * 1024 * 1024
SIZE_BUDGET_S = 3.0

# Verified against setup_env / tools: under %LOCALAPPDATA%\Unweave the installer and
# first-run setup create permanent `packages/`, `ffmpeg/`, `models/` and `ui.json`.
# FFmpeg archives land in system temp as `unweave-ffmpeg-*` (not app-data). Model
# downloads stage as `.model-download-*` inside the models folder. pip --prefix
# installs straight into `packages/` and does not leave `.packages-*` or `pip-*`
# folders there, so those patterns are intentionally omitted.


@dataclass(frozen=True)
class Pattern:
    group: str
    patterns: tuple[str, ...]
    kind: str  # "folder" | "file"


TEMP_PATTERNS = Pattern(
    "temp",
    ("unweave-*", "unweave-ffmpeg-*", "unweave-upload-*",
     "sound-razor-*", "sound-razor-ffmpeg-*"),
    "folder",
)
PROJECTS_ROOT_PATTERNS = Pattern(
    "interrupted",
    (".separation-*", ".youtube-*", ".import-*", ".exports-*",
     ".guitar-split-*", ".stems-*"),
    "folder",
)
PROJECT_FOLDER_PATTERNS = Pattern(
    "interrupted",
    (".separation-*", ".exports-*", ".guitar-split-*", ".stems-*"),
    "folder",
)
PROJECT_COVER_PATTERNS = Pattern("interrupted", (".cover-*",), "file")
MODEL_PATTERNS = Pattern("downloads", (".model-download-*",), "folder")


def cleanup_temp_dir() -> Path:
    """Temp root for leftover scans. Override with UNWEAVE_CLEANUP_TEMP (tests / safe UI)."""
    override = os.environ.get("UNWEAVE_CLEANUP_TEMP")
    if override:
        return Path(override).expanduser().resolve()
    return Path(tempfile.gettempdir()).resolve()


def _matches(name: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(name, pattern) for pattern in patterns)


def item_id(path: Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8", "replace")).hexdigest()[:20]


def _entry_bytes(path: Path, kind: str, deadline: float) -> int | None:
    """Return size, or None if the size budget ran out."""
    if time.monotonic() > deadline:
        return None
    if kind == "file":
        try:
            return path.stat().st_size if path.is_file() and not is_link_like(path) else 0
        except OSError:
            return 0
    return dir_bytes(path)


def _age_hours(path: Path) -> float | None:
    try:
        return max(0.0, (time.time() - path.stat().st_mtime) / 3600)
    except OSError:
        return None


def _list_top(folder: Path) -> list[Path]:
    try:
        if is_link_like(folder) or not folder.is_dir():
            return []
        return list(folder.iterdir())
    except OSError:
        return []


def _candidate(path: Path, group: str, kind: str, *, min_age_hours: float,
               deadline: float) -> dict | None:
    try:
        if is_link_like(path):
            return None
        if kind == "folder" and not path.is_dir():
            return None
        if kind == "file" and not path.is_file():
            return None
    except OSError:
        return None
    age = _age_hours(path)
    if age is None or age < min_age_hours:
        return None
    size = _entry_bytes(path, kind, deadline)
    if size is None:
        return {"id": item_id(path), "group": group, "path": str(path), "bytes": None,
                "count": 1, "kind": kind, "age_hours": round(age, 2), "truncated": True}
    return {"id": item_id(path), "group": group, "path": str(path), "bytes": size,
            "count": 1, "kind": kind, "age_hours": round(age, 2), "truncated": False}


def scan(*, projects_root: Path | None, model_cache: Path | None,
         app_data: Path | None = None, temp_dir: Path | None = None,
         min_age_hours: float = AGE_HOURS,
         jobs_busy: bool = False, include_temp: bool = True) -> dict:
    """Return leftover candidates. When ``jobs_busy``, returns an empty proposal."""
    started = time.time()
    deadline = time.monotonic() + SIZE_BUDGET_S
    if jobs_busy:
        return {"items": [], "bytes": 0, "count": 0, "scanned_at": started, "truncated": False}

    temp_dir = Path(temp_dir) if temp_dir is not None else cleanup_temp_dir()
    app_data = Path(app_data) if app_data is not None else app_data_dir()
    items: list[dict] = []
    truncated = False

    def add(path: Path, pattern: Pattern):
        nonlocal truncated
        if not _matches(path.name, pattern.patterns):
            return
        item = _candidate(path, pattern.group, pattern.kind,
                          min_age_hours=min_age_hours, deadline=deadline)
        if item is None:
            return
        if item.get("truncated"):
            truncated = True
        items.append(item)

    if include_temp:
        for entry in _list_top(temp_dir):
            add(entry, TEMP_PATTERNS)

    if projects_root is not None:
        root = Path(projects_root)
        for entry in _list_top(root):
            add(entry, PROJECTS_ROOT_PATTERNS)
            # Per-project staging lives inside each song folder.
            if entry.is_dir() and not is_link_like(entry) and not entry.name.startswith("."):
                for child in _list_top(entry):
                    add(child, PROJECT_FOLDER_PATTERNS)
                    add(child, PROJECT_COVER_PATTERNS)

    if model_cache is not None:
        for entry in _list_top(Path(model_cache)):
            add(entry, MODEL_PATTERNS)

    # App-data unfinished names: none today beyond models/ (documented above).
    _ = app_data

    known = {item["bytes"] for item in items if item.get("bytes") is not None}
    total = sum(item["bytes"] or 0 for item in items)
    return {
        "items": items,
        "bytes": total,
        "count": len(items),
        "scanned_at": started,
        "truncated": truncated,
        "more_than": truncated and (max(known) if known else total),
    }


def qualifies(path: Path, *, min_age_hours: float = AGE_HOURS,
              projects_root: Path | None = None,
              model_cache: Path | None = None,
              temp_dir: Path | None = None) -> str | None:
    """Return None if ``path`` may be deleted, else a skip reason."""
    temp_dir = Path(temp_dir) if temp_dir is not None else cleanup_temp_dir()
    try:
        if is_link_like(path):
            return "link"
    except OSError:
        return "unreadable"
    age = _age_hours(path)
    if age is None:
        return "unreadable"
    if age < min_age_hours:
        return "too_new"

    name = path.name
    parent = path.parent

    def under(root: Path | None) -> bool:
        if root is None:
            return False
        try:
            return parent.resolve() == Path(root).resolve()
        except OSError:
            return False

    if under(temp_dir) and _matches(name, TEMP_PATTERNS.patterns) and path.is_dir():
        return None
    if under(model_cache) and _matches(name, MODEL_PATTERNS.patterns) and path.is_dir():
        return None
    if projects_root is not None:
        root = Path(projects_root)
        if under(root) and _matches(name, PROJECTS_ROOT_PATTERNS.patterns) and path.is_dir():
            return None
        try:
            if parent.parent.resolve() == root.resolve() and not parent.name.startswith("."):
                if _matches(name, PROJECT_FOLDER_PATTERNS.patterns) and path.is_dir():
                    return None
                if _matches(name, PROJECT_COVER_PATTERNS.patterns) and path.is_file():
                    return None
        except OSError:
            return "unreadable"
    return "not_leftover"


def clean(ids: list[str] | None, *, previous: dict,
          projects_root: Path | None, model_cache: Path | None,
          temp_dir: Path | None = None, min_age_hours: float = AGE_HOURS,
          jobs_busy: bool = False) -> dict:
    """Re-validate and delete. ``previous`` is the last scan result."""
    if jobs_busy:
        raise ValueError("Wait for the current job to finish or cancel it before cleaning leftovers.")
    by_id = {item["id"]: item for item in previous.get("items", [])}
    targets = list(by_id.values()) if not ids else [by_id[i] for i in ids if i in by_id]
    freed = 0
    removed: list[str] = []
    skipped: list[dict] = []
    for item in targets:
        path = Path(item["path"])
        reason = qualifies(path, min_age_hours=min_age_hours, projects_root=projects_root,
                           model_cache=model_cache, temp_dir=temp_dir)
        if reason:
            skipped.append({"id": item["id"], "reason": reason})
            continue
        if item_id(path) != item["id"]:
            skipped.append({"id": item["id"], "reason": "changed"})
            continue
        try:
            size = dir_bytes(path) if item["kind"] == "folder" else path.stat().st_size
            if item["kind"] == "folder":
                shutil.rmtree(path)
            else:
                path.unlink()
            freed += size
            removed.append(item["id"])
        except OSError as error:
            skipped.append({"id": item["id"], "reason": str(error)})
    return {"freed_bytes": freed, "removed": removed, "skipped": skipped}


def sections_for_startup(*, updates_should_prompt: bool, cleanup_bytes: int,
                         cleanup_auto: bool, cleanup_dont_ask: bool) -> dict:
    """Pure decision helper for the startup dialog (also unit-tested)."""
    show_updates = bool(updates_should_prompt)
    show_cleanup = (
        cleanup_bytes >= SILENT_BYTES
        and not cleanup_auto
        and not cleanup_dont_ask
    )
    silent_cleanup = (
        cleanup_bytes > 0
        and (
            cleanup_bytes < SILENT_BYTES
            or (cleanup_auto and not cleanup_dont_ask)
        )
    )
    return {
        "show_updates": show_updates,
        "show_cleanup": show_cleanup,
        "silent_cleanup": silent_cleanup,
        "open": show_updates or show_cleanup,
    }
