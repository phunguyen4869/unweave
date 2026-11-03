"""Copy-only diagnostics bundle for in-app error reports (spec 15)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import platform
import sys

from .updates import GITHUB_OWNER, GITHUB_REPO

LOG_LINE_CAP = 80
LOG_BYTE_CAP = 32 * 1024
ISSUES_NEW_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/issues/new"


def redact_text(text: str, projects_root: Path | None) -> str:
    """Replace the projects folder prefix with ``<projects>/`` (both slash styles)."""
    if not text or projects_root is None:
        return text
    candidates = [projects_root]
    try:
        candidates.append(projects_root.resolve())
    except OSError:
        pass
    forms: set[str] = set()
    for root in candidates:
        raw = str(root)
        if not raw:
            continue
        forms.update({raw, raw.replace("\\", "/"), raw.replace("/", "\\")})
        # Windows paths in logs often keep the drive letter with either slash.
        if len(raw) >= 2 and raw[1] == ":":
            forms.add(raw.replace("\\", "/"))
            forms.add(raw[:2] + raw[2:].replace("\\", "/"))
    redacted = text
    for form in sorted(forms, key=len, reverse=True):
        if form and form in redacted:
            redacted = redacted.replace(form, "<projects>")
    return redacted


def trim_log_lines(lines: list[str], *, max_lines: int = LOG_LINE_CAP,
                   max_bytes: int = LOG_BYTE_CAP) -> list[str]:
    """Keep the newest lines within the line and byte caps."""
    if not lines:
        return []
    chosen = list(lines[-max(1, max_lines):])
    while chosen and sum(len(line) + 1 for line in chosen) > max_bytes:
        chosen.pop(0)
    return chosen


def _stage_flag(stages: list[dict] | None, stage_id: str) -> str:
    for stage in stages or []:
        if stage.get("id") == stage_id:
            if stage.get("done"):
                return "ok"
            if stage.get("missing"):
                return "missing"
            return "unknown"
    return "—"


def build_diagnostics_text(
    *,
    version: str,
    platform_name: str,
    arch: str,
    python_version: str,
    vcruntime: str | None = None,
    utc_now: datetime | None = None,
    setup_stages: list[dict] | None = None,
    job: dict | None = None,
    log_lines: list[str] | None = None,
    projects_root: Path | None = None,
) -> str:
    """Build the plain-text diagnostics block (English labels)."""
    when = utc_now or datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    else:
        when = when.astimezone(timezone.utc)
    stamp = when.strftime("%Y-%m-%d %H:%M:%S UTC")

    setup = (
        f"runtime={_stage_flag(setup_stages, 'runtime')} "
        f"ffmpeg={_stage_flag(setup_stages, 'ffmpeg')} "
        f"separation={_stage_flag(setup_stages, 'separation')} "
        f"youtube={_stage_flag(setup_stages, 'youtube')}"
    )

    if job:
        kind = job.get("kind") or "—"
        status = job.get("status") or "—"
        error = redact_text(str(job.get("error") or "—"), projects_root)
        last_job = f"kind={kind} status={status} error={error}"
    else:
        last_job = "kind=— status=— error=—"

    logs = trim_log_lines(list(log_lines or []))
    redacted_logs = [redact_text(line, projects_root) for line in logs]
    log_block = "\n".join(redacted_logs) if redacted_logs else "(no recent log lines)"

    return (
        "=== Unweave diagnostics ===\n"
        f"App version: {version}\n"
        f"Platform: {platform_name}\n"
        f"Arch: {arch}\n"
        f"Python: {python_version}\n"
        f"VC++ runtime: {vcruntime or '—'}\n"
        f"App clock (UTC): {stamp}\n"
        f"Setup: {setup}\n"
        f"Last job: {last_job}\n"
        "--- recent log (last N lines) ---\n"
        f"{log_block}\n"
        "=== end ===\n"
    )


def host_platform_name() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def host_arch() -> str:
    return platform.machine() or "unknown"


def host_python() -> str:
    return sys.version.split()[0]
