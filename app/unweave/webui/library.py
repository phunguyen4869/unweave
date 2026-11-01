"""Project library state, job queue, and progress parsing for the local web UI."""

from collections import deque
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from ..projects import (atomic_json, describe_project, import_project, list_projects,
                        project_path, save_metadata, cover_path, metadata_fields, stem_file)
from ..projects.metadata import MetadataLookup
from ..audio.sources import youtube_url, youtube_command
from ..audio.pipeline import probe_duration, parse_trim
from ..audio.exports import FORMATS, export_stems
from ..tools import (MISSING_FFMPEG, PCM_BYTES_PER_SECOND, app_version, ensure_ffmpeg_on_path,
                     env_first, require_free_space, total_ram_gb)
from ..processes import popen, stop as stop_process
from ..setup_env import (FFMPEG_SIZE_MB, RUNTIME_SIZE_MB, SEPARATION_SIZE_MB, YOUTUBE_SIZE_MB,
                         ffmpeg_ok, runtime_ok, separation_ok, youtube_ok, run_setup, torch_has_cuda)
from ..updates import (ASK_AGAIN_S, CHECK_INTERVAL_S, RELEASES_LATEST_PAGE, fetch_latest_release,
                       is_newer, normalize_tag)

CUSTOM_STEMS = ("vocals", "guitar", "bass", "drums", "piano", "other")
# Export output size relative to the stored FLAC stem, per format (rounded up).
EXPORT_SIZE_FACTOR = {"flac": 1.0, "wav16": 2.0, "aiff": 2.0, "mp3": 0.3, "opus": 0.2, "m4a": 0.25}
# A plan may also name the guitar-split outputs, both as own files and as group
# members; they are produced mid-run by the split, not by the separation model.
PLAN_STEMS = (*CUSTOM_STEMS, "lead", "rhythm")

# Staging-directory prefixes left behind by interrupted runs. The startup sweep only
# removes directories matching these prefixes, never follows symlinks, and never
# deletes outside the projects root.
STALE_STAGING_PREFIXES = (
    ".separation-", ".youtube-", ".import-", ".exports-", ".guitar-split-",
    ".stems-", ".model-download-",
)
STALE_STAGING_MAX_AGE_HOURS = 24


def selection_stems(preset, stems=None):
    if preset == "vocals":
        return ["vocals", "instrumental"]
    if preset != "custom":
        raise ValueError("Choose vocals/instrumental or custom separation.")
    if not isinstance(stems, list) or not stems:
        raise ValueError("Select at least one instrument.")
    unknown = [stem for stem in stems
               if not isinstance(stem, str) or stem not in CUSTOM_STEMS]
    if unknown:
        raise ValueError(f"Unknown custom stem: {', '.join(map(str, unknown))}.")
    return list(dict.fromkeys(stems))


def validate_group(group):
    """None keeps the legacy `--stems other,…` folding; a list is an explicit plan."""
    if group is None:
        return None
    if not isinstance(group, list):
        raise ValueError("Invalid stem plan.")
    unknown = [name for name in group
               if not isinstance(name, str) or name not in PLAN_STEMS]
    if unknown:
        raise ValueError(f"Unknown stem in the plan: {', '.join(map(str, unknown))}.")
    return list(dict.fromkeys(group))


def plan_stems(preset, stems, group=None):
    """Own files for a job. An explicit plan may keep none of them, as long as
    something is folded; the empty list is then deliberate, not a mistake."""
    if group is None:
        return selection_stems(preset, stems)
    if not isinstance(stems, list):
        raise ValueError("Invalid stem plan.")
    # `lead`/`rhythm` are legal own files: they arrive from the guitar split.
    unknown = [stem for stem in stems
               if not isinstance(stem, str) or stem not in PLAN_STEMS]
    if unknown:
        raise ValueError(f"Unknown stem in the plan: {', '.join(map(str, unknown))}.")
    chosen = list(dict.fromkeys(stems))
    if not chosen and not group:
        raise ValueError("Select at least one instrument.")
    return chosen


# tqdm bars from audio-separator, e.g. " 45%|████▌     | 23/51 [00:12<00:15,  1.80it/s]"
TQDM = re.compile(r"(\d{1,3})%\|[^|]*\|[^\[]*\[([\d:]+)<([\d:]+|\?)")
GUITAR_PROGRESS = re.compile(r"^Guitar split (\d{1,3})%")
# (marker printed by the CLI, phase, overall progress when the phase starts)
# Prepare/load are short on a warm run — keep their floors small so inference owns the bar.
PHASE_MARKERS = (("Preparing audio", "prepare", 1), ("Loading model", "load", 3),
                 ("Downloading ", "download", 3), ("Separating with", "separate", 5),
                 ("Splitting guitar", "guitar", 5), ("Writing stems", "finalize", 96),
                 ("Exporting stems", "export", 2), ("Exported ", "finalize", 96))
# Overall job.progress maps measured inference elapsed/(elapsed+ETA) into this band.
# step_progress (detail ring) stays 0-100 per pass and does not use this range.
SEPARATE_RANGE = (5, 95)
# Prior only: used to project the not-yet-started guitar pass while Demucs is running.
# Once the guitar pass reports timing, real elapsed/ETA replace this ratio.
GUITAR_TIME_RATIO = 10.0
FINALIZE_FUDGE = 3.0  # writing stems afterwards takes a few seconds
YTDLP_PROGRESS = re.compile(r"\[download\]\s+([\d.]+)%(?:.*ETA\s+([\d:]+))?")


def clock_seconds(text: str):
    try:
        parts = [int(part) for part in text.split(":")]
    except ValueError:
        return None
    total = 0
    for part in parts:
        total = total * 60 + part
    return total


APP_VERSION = app_version()
# How many per-job log files to keep on disk. Logs are small text files, but a
# long-lived install can run thousands of jobs, so keep only the recent ones.
JOB_LOG_KEEP = 40


class JobLog:
    """A per-job transcript on disk, so a run can be diagnosed after the fact.

    The UI's in-memory log is trimmed to 160 lines, drops the progress lines that
    drive the bar, and dies with the server process (a cancelled or crashed job
    leaves nothing behind). This file keeps every raw CLI line plus the command
    that produced it.
    """

    def __init__(self, directory: Path, job: dict, command):
        self.path = None
        self.handle = None
        try:
            directory.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(job.get("started") or time.time()))
            safe = re.sub(r"[^\w.-]+", "-", f"{stamp}-{job['kind']}-{job['id']}").strip("-")
            self.path = directory / f"{safe}.log"
            self.handle = self.path.open("w", encoding="utf-8", errors="replace", buffering=1)
            self.write(f"# job      {job['id']} ({job['kind']})")
            if job.get("project"):
                self.write(f"# project  {job['project']}")
            self.write(f"# started  {stamp}  app {APP_VERSION}")
            self.write("# command  " + " ".join(str(part) for part in command))
            self.write("")
            job["log"] = str(self.path)
        except OSError:
            self.handle = None

    def write(self, line: str):
        if self.handle is None:
            return
        try:
            stamp = time.strftime("%H:%M:%S")
            self.handle.write(f"{stamp} {line}\n")
        except OSError:
            self.handle = None

    def close(self, status: str, error=None):
        if self.handle is None:
            return
        try:
            self.write("")
            self.write(f"# status   {status}" + (f": {error}" if error else ""))
            self.handle.close()
        except OSError:
            pass
        finally:
            self.handle = None


def prune_job_logs(directory: Path, keep: int = JOB_LOG_KEEP):
    """Delete all but the newest `keep` job logs. Never raises."""
    try:
        logs = sorted(directory.glob("*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
        for stale in logs[keep:]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass



def public_job(job: dict) -> dict:
    """A job record for the API: worker-only "_" fields hold Paths, which JSON can't encode."""
    return {key: value for key, value in job.items() if not key.startswith("_")}


class Library:
    def __init__(self, root: Path | None, config: Path, cache: Path, default_root: Path = Path("output"),
                 window=None):
        self.lock = threading.RLock()
        self.config = config.resolve()
        self.cache = cache.resolve()
        self.default_root = default_root.resolve()
        # Set by ui_entrypoint.py when running as a desktop window (None for the plain
        # `unweave ui` browser CLI). Lets the custom title bar's minimize/maximize/
        # close/drag buttons reach the window over the same HTTP API as everything else,
        # instead of depending on pywebview's own JS bridge (unreliable in practice:
        # window.pywebview never actually materializes in this environment).
        self.window = window
        self.root = None
        # Job queue: pending jobs (status "queued") in FIFO order, plus active jobs.
        # Phase 2 of spec 05 supports a configurable concurrency cap (default 1),
        # so `self.processes` maps job_id -> subprocess and `self.active` is a set
        # of active job ids. Each active job runs in its own worker thread.
        self.queue = []              # pending job records
        self.active = set()          # set of active job ids
        self.active_jobs = {}        # job_id -> job record for active jobs
        self.processes = {}          # job_id -> subprocess.Popen
        self.job_logs = {}           # job_id -> deque(maxlen=160)
        # Per-job transcripts on disk (see JobLog). Kept next to the config file so
        # dev runs and installs both leave a trail; overridable for tests.
        self.log_dir = Path(env_first("UNWEAVE_LOG_DIR", "SOUND_RAZOR_LOG_DIR")
                            or self.config.parent / "logs")
        self.finished_jobs = deque(maxlen=20)  # recent finished records, for UI notices
        self._drainer = None         # coordinator thread that starts workers up to cap
        self._job_done = threading.Event()  # set when any active job finishes
        self.max_concurrent_jobs = self._derive_max_concurrent_jobs()
        # Backward-compat aliases used by setup_env.py: while a job runs these point at
        # the most recently started active job's record / logs / process.
        self.job = None
        self.logs = deque(maxlen=160)
        self.process = None
        self.lookup = MetadataLookup()
        if root is not None:
            self.set_root(str(root), create=True)
        elif self.config.exists():
            try:
                saved = Path(json.loads(self.config.read_text(encoding='utf-8'))["root"])
                if saved.is_dir():
                    self.root = saved.resolve()
            except (ValueError, KeyError, OSError):
                pass
        if self.root is None:
            try:
                self.set_root(str(self.default_root), create=True)
            except (ValueError, OSError):
                pass
        # Sweep staging directories left behind by interrupted runs on startup.
        if self.root is not None:
            self.sweep_stale_staging()

    def _derive_max_concurrent_jobs(self) -> int:
        """Derive suggested default concurrency cap.

        - 1 on CPU-only machines
        - 2-3 when torch.cuda.is_available()
        - Never more than max(1, available_ram_gb // 3)
        Override with UNWEAVE_MAX_CONCURRENT_JOBS (or legacy SOUND_RAZOR_MAX_CONCURRENT_JOBS).
        """
        override = env_first("UNWEAVE_MAX_CONCURRENT_JOBS", "SOUND_RAZOR_MAX_CONCURRENT_JOBS")
        if override:
            try:
                return max(1, int(override))
            except ValueError:
                pass
        cap = 3 if torch_has_cuda() else 1
        ram_cap = max(1, int(total_ram_gb() // 3))
        return min(cap, ram_cap)

    def running(self):
        return bool(self.active)

    def _active_jobs(self) -> list[dict]:
        """Return the job records for all active job ids."""
        return [self.active_jobs[jid] for jid in self.active if jid in self.active_jobs]

    def set_root(self, value: str, create=False):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Choose a projects folder.")
        with self.lock:
            if self.running():
                raise ValueError("Wait for the current job to finish or cancel it before changing folders.")
            root = Path(value).expanduser().resolve()
            if create:
                root.mkdir(parents=True, exist_ok=True)
            if not root.is_dir():
                raise ValueError("Folder does not exist. Enable ‘Create folder’ to create it.")
            # Check readable listing now, before persisting the selection.
            list(root.iterdir())
            data = self._load_config()
            data["root"] = str(root)
            self._save_config(data)
            self.root = root
            self.job = None

    def require_root(self):
        if self.root is None:
            raise ValueError("Choose a projects folder first.")
        return self.root

    # ---------------------------------------------------------------- updates (spec 10)

    def _load_config(self) -> dict:
        if not self.config.exists():
            return {}
        try:
            data = json.loads(self.config.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (ValueError, OSError):
            return {}

    def _save_config(self, data: dict):
        self.config.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(self.config, data)

    def _updates_section(self) -> dict:
        section = self._load_config().get("updates")
        return dict(section) if isinstance(section, dict) else {}

    def _write_updates(self, updates: dict):
        data = self._load_config()
        data["updates"] = updates
        self._save_config(data)

    def updates_status(self) -> dict:
        """Prefs + last known release, with no network call."""
        with self.lock:
            cfg = self._updates_section()
            current = APP_VERSION
            latest = normalize_tag(cfg.get("latest_tag"))
            dismissed = normalize_tag(cfg.get("dismissed_tag"))
            available = bool(latest and is_newer(latest, current) and latest != dismissed)
            mode = cfg.get("check") if cfg.get("check") in {"auto", "manual", "ask"} else "ask"
            ask_again_at = cfg.get("ask_again_at")
            try:
                ask_again_at = float(ask_again_at) if ask_again_at is not None else None
            except (TypeError, ValueError):
                ask_again_at = None
            last_checked_at = cfg.get("last_checked_at")
            try:
                last_checked_at = float(last_checked_at) if last_checked_at is not None else None
            except (TypeError, ValueError):
                last_checked_at = None
            now = time.time()
            should_prompt = mode == "ask" and (ask_again_at is None or ask_again_at <= now)
            due = last_checked_at is None or (now - last_checked_at) >= CHECK_INTERVAL_S
            should_auto_check = mode == "auto" and due
            return {
                "check": mode,
                "current": current,
                "latest": latest or None,
                "url": cfg.get("latest_url") or RELEASES_LATEST_PAGE,
                "available": available,
                "last_checked_at": last_checked_at,
                "ask_again_at": ask_again_at,
                "should_prompt": should_prompt,
                "should_auto_check": should_auto_check,
            }

    def set_updates_prefs(self, data: dict | None) -> dict:
        """Persist consent / dismiss choices into ui.json."""
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        with self.lock:
            cfg = self._updates_section()
            mode = data.get("check")
            if mode is not None:
                if mode not in {"auto", "manual", "ask"}:
                    raise ValueError('updates.check must be "auto", "manual", or "ask".')
                cfg["check"] = mode
                if mode == "auto":
                    cfg.pop("ask_again_at", None)
                elif mode == "ask":
                    delay = data.get("ask_again_in", ASK_AGAIN_S)
                    try:
                        delay = float(delay)
                    except (TypeError, ValueError):
                        delay = ASK_AGAIN_S
                    cfg["ask_again_at"] = time.time() + max(0.0, delay)
                else:
                    cfg.pop("ask_again_at", None)
            if "dismissed_tag" in data:
                tag = normalize_tag(data.get("dismissed_tag"))
                if tag:
                    cfg["dismissed_tag"] = tag
                else:
                    cfg.pop("dismissed_tag", None)
            self._write_updates(cfg)
            return self.updates_status()

    def check_updates(self, manual: bool = False, opener=None) -> dict:
        """Fetch the latest stable release when allowed; persist the result.

        Auto checks are quiet on failure (return status without raising). Manual
        checks surface errors to the caller.
        """
        with self.lock:
            status = self.updates_status()
            mode = status["check"]
            if not manual and mode != "auto":
                return status
            if not manual and not status["should_auto_check"]:
                return status

        try:
            release = fetch_latest_release(
                user_agent=f"Unweave/{APP_VERSION or 'dev'}",
                opener=opener,
            )
        except ValueError:
            if manual:
                raise
            return self.updates_status()

        with self.lock:
            cfg = self._updates_section()
            cfg["latest_tag"] = release["tag"]
            cfg["latest_url"] = release["url"]
            cfg["last_checked_at"] = time.time()
            self._write_updates(cfg)
            return self.updates_status()

    def sweep_stale_staging(self, max_age_hours: int | None = None) -> list[str]:
        """Remove stale staging directories left behind by interrupted runs.

        Only directories under ``self.root`` whose names match a known staging
        prefix are considered, symlinks are never followed, and nothing outside
        the projects root is ever deleted. Returns the list of removed paths.
        """
        max_age_hours = STALE_STAGING_MAX_AGE_HOURS if max_age_hours is None else max_age_hours
        if self.root is None or not self.root.is_dir():
            return []
        cutoff = time.time() - max_age_hours * 3600
        removed: list[str] = []
        for entry in self.root.iterdir():
            if not entry.is_dir() or entry.is_symlink():
                continue
            if not entry.name.startswith(STALE_STAGING_PREFIXES):
                continue
            try:
                mtime = entry.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                continue
            try:
                shutil.rmtree(entry)
                removed.append(str(entry))
            except OSError:
                # Best effort: a locked/in-use staging dir stays for diagnosis.
                pass
        return removed

    def require_matching_root(self, expected_root):
        root = self.require_root()
        if expected_root != str(root):
            raise ValueError("The projects folder changed. Refresh the library and reopen this action.")
        return root

    def _job_logs(self, job_id: str) -> deque:
        return self.job_logs.setdefault(job_id, deque(maxlen=160))

    def state(self):
        with self.lock:
            jobs = []
            for job_id in self.active:
                job = self.active_jobs.get(job_id)
                if not job:
                    continue
                active = public_job(job)
                active["position"] = 0
                active["logs"] = list(self._job_logs(job_id))
                jobs.append(active)
            for index, job in enumerate(self.queue, start=1):
                record = public_job(job)
                record["position"] = index
                record["logs"] = list(self._job_logs(job["id"]))
                jobs.append(record)
            # `job` shim: the most recently started active job so success/failure
            # notices still surface after workers exit.
            job_shim = public_job(self.job) if self.job else None
            return {"root": str(self.root) if self.root else None, "default_root": str(self.default_root),
                    "projects": list_projects(self.root) if self.root else [], "jobs": jobs,
                    "active_job": next(iter(self.active)) if self.active else None,
                    "active_jobs": [jid for jid in self.active],
                    "max_concurrent_jobs": self.max_concurrent_jobs,
                    "job": job_shim,
                    "finished_jobs": [public_job(job) for job in self.finished_jobs],
                    "setup": self.setup_status(), "version": APP_VERSION, "now": time.time()}

    def _track_progress(self, job: dict, line: str) -> bool:
        """Update a specific job's phase/progress/ETA from a CLI output line.
        True hides the line from the log."""
        for marker, phase, floor in PHASE_MARKERS:
            if line.startswith(marker):
                job["phase"] = phase
                job["progress"] = max(job["progress"], floor)
                # Every step owns its own 0-100: the dialog's ring restarts for the
                # guitar pass instead of counting one global bar, so a long second
                # pass is visibly its own stage rather than a stalled first one.
                # Only stages that report real sub-progress reset the ring; prepare/
                # load/save keep the finished value so it never jumps back to 0.
                if phase in {"separate", "guitar", "download", "export"}:
                    job["step_progress"] = 0
                    job["step_eta"] = None
                if phase == "guitar":
                    self._lock_demucs_elapsed(job)
                    job["pass_index"] = max(int(job.get("pass_index") or 1), 2)
                    job["progress"] = max(job["progress"], SEPARATE_RANGE[0])
                if phase in {"separate", "guitar"}:
                    job["phase_started"] = time.time()
                if phase in {"finalize", "download"}:
                    job["eta"] = None
                    job["step_eta"] = None
                return False
        bar = TQDM.search(line)
        guitar = GUITAR_PROGRESS.match(line)
        step = bar or guitar
        if not step:
            return False
        if job["phase"] in {"separate", "guitar"}:
            # Time the ETA extrapolation from the start of *this* pass. Measuring from
            # the start of the phase made the guitar pass inherit the whole Demucs run:
            # at 15% of the split it reported that Demucs' minutes had to be repeated
            # for the remaining 85%, so TIME LEFT swelled to ~12 minutes.
            sample = "guitar" if guitar else "demucs"
            if job.get("sample") != sample:
                if sample == "guitar":
                    self._lock_demucs_elapsed(job)
                job["sample"] = sample
                job["sample_started"] = time.time()
            percent = min(100, int(step.group(1)))
            job["step_progress"] = max(job.get("step_progress") or 0, percent)
            bar_elapsed = clock_seconds(bar.group(2)) if bar else None
            spent = bar_elapsed if bar_elapsed is not None else (
                time.time() - job.get("sample_started", job["started"]))
            remaining = clock_seconds(bar.group(3)) if bar else None
            if remaining is None and percent:
                remaining = spent * (100 - percent) / percent
            if remaining is not None:
                self._apply_time_weighted_progress(job, percent, spent, remaining, bool(guitar))
        return True

    @staticmethod
    def _lock_demucs_elapsed(job: dict):
        """Remember how long the stem pass took before the guitar sample clock resets."""
        if not job.get("split_leaves") or job.get("demucs_elapsed") is not None:
            return
        start = job.get("sample_started") or job.get("phase_started") or job.get("started")
        if start is None:
            job["demucs_elapsed"] = 0.0
            return
        job["demucs_elapsed"] = max(0.0, time.time() - start)

    @staticmethod
    def _apply_time_weighted_progress(job: dict, percent: int, spent: float,
                                      remaining: float, guitar: bool):
        """Map overall progress from inference elapsed/(elapsed+remaining).

        While Demucs is running and a guitar pass is still queued, project that
        pass with GUITAR_TIME_RATIO (prior only). Once the guitar pass has a
        usable wall clock, measured Demucs duration + live guitar remaining
        replace the ratio. The first guitar ticks often have spent≈0 (sample
        clock just reset), so keep the prior until spent is meaningful.
        """
        low, high = SEPARATE_RANGE
        split = bool(job.get("split_leaves"))
        on_guitar = guitar or job.get("phase") == "guitar"
        spent = max(0.0, spent)
        remaining = max(0.0, remaining)

        # step_eta is pass-local remaining (no finalize fudge). eta stays whole-job.
        # eta_estimated is True while the guitar prior still pads the whole-job ETA.
        if on_guitar and split:
            demucs_elapsed = float(job.get("demucs_elapsed") or 0.0)
            if spent >= 1.0 and percent > 0:
                done, left = demucs_elapsed + spent, remaining
                step_left, eta_estimated = remaining, False
            elif percent > 0 and demucs_elapsed > 0:
                est_guitar = demucs_elapsed * GUITAR_TIME_RATIO
                done = demucs_elapsed + est_guitar * (percent / 100.0)
                left = est_guitar * (1.0 - percent / 100.0)
                step_left, eta_estimated = left, True
            else:
                done, left = demucs_elapsed, demucs_elapsed * GUITAR_TIME_RATIO
                step_left, eta_estimated = left, True
        elif on_guitar:
            # Split-only: one pass owns the whole inference band (no Demucs prior).
            done, left = spent, remaining
            step_left, eta_estimated = remaining, False
        elif split:
            if percent > 0:
                est_demucs_total = spent / (percent / 100.0)
            else:
                est_demucs_total = spent
            prior_guitar = est_demucs_total * GUITAR_TIME_RATIO
            done, left = spent, remaining + prior_guitar
            step_left, eta_estimated = remaining, True
            if percent >= 100:
                job["demucs_elapsed"] = max(float(job.get("demucs_elapsed") or 0.0), spent)
        else:
            done, left = spent, remaining
            step_left, eta_estimated = remaining, False

        total = done + left
        last_pass_done = percent >= 100 and not (split and not on_guitar)
        if last_pass_done:
            mapped = high
        elif total > 0:
            mapped = low + (high - low) * (done / total)
        else:
            mapped = low
        job["progress"] = max(job["progress"], min(high, mapped))
        job["eta"] = left + FINALIZE_FUDGE
        job["eta_at"] = time.time()
        job["step_eta"] = step_left
        job["step_eta_at"] = time.time()
        job["eta_estimated"] = eta_estimated

    # ------------------------------------------------------------------ enqueue

    def _enqueue(self, job: dict):
        """Append a queued job and start the drainer thread if it is not running."""
        self.queue.append(job)
        self._ensure_drainer()
        return public_job(job)

    def _ensure_drainer(self):
        if self._drainer is None or not self._drainer.is_alive():
            self._drainer = threading.Thread(target=self._drain, daemon=True)
            self._drainer.start()

    def _drain(self):
        """Start worker threads for queued jobs up to max_concurrent_jobs.

        Exits when the queue is empty and no active jobs remain.
        """
        while True:
            with self.lock:
                if not self.queue and not self.active:
                    self._drainer = None
                    self.process = None
                    self.logs = deque(maxlen=160)
                    return
                started = []
                while len(self.active) < self.max_concurrent_jobs:
                    job = self._next_startable()
                    if job is None:
                        break
                    self.queue.remove(job)
                    self.active.add(job["id"])
                    self.active_jobs[job["id"]] = job
                    job["status"] = "running"
                    job["started"] = time.time()
                    self.job_logs.setdefault(job["id"], deque(maxlen=160))
                    # Backward-compat shims point to the latest started job.
                    self.job = job
                    self.logs = self._job_logs(job["id"])
                    started.append(job)
            if not started:
                # All cap slots filled; wait for a worker to signal completion.
                self._job_done.wait(timeout=1.0)
                self._job_done.clear()
                continue
            for job in started:
                thread = threading.Thread(target=self._run_job, args=(job,), daemon=True)
                thread.start()

    def _next_startable(self):
        """First queued job that may start now, keeping FIFO order where it matters.

        Setup runs alone: it reinstalls packages the other jobs import, and
        setup_env reports through the single `self.job`/`self.logs`/`self.process`
        aliases. Two jobs on one project never overlap, because each one swaps
        the project's whole stems folder when it publishes.
        """
        active = self._active_jobs()
        if any(job["kind"] == "setup" for job in active):
            return None
        busy = {job.get("project") for job in active if job.get("project")}
        for job in self.queue:
            if job["kind"] == "setup":
                # Wait for running jobs to drain; nothing queued after setup jumps it.
                return None if active else job
            if job.get("project") and job["project"] in busy:
                continue
            return job
        return None

    def _finish(self, job: dict):
        """Mark a worker's own job record finished. Caller holds the lock."""
        if job["status"] == "cancelling":
            job["status"] = "cancelled"
        job["finished"] = time.time()
        self.processes.pop(job["id"], None)
        self.finished_jobs.append(job)
        prune_job_logs(self.log_dir)
        # Point the UI's single-job shim at the finished job unless another is still running,
        # so its success/failure notice still surfaces.
        others = [other for other in self._active_jobs() if other is not job]
        if not others:
            self.job = job

    def _launch(self, job: dict, command, **options):
        """Start a job's subprocess unless it is being cancelled. Caller holds the lock."""
        if job["status"] == "cancelling":
            return None
        process = popen(command, **options)
        self.processes[job["id"]] = process
        self.process = process
        return process

    def _run_job(self, job: dict):
        """Run a single job's worker, then signal completion and clean up."""
        job_id = job["id"]
        kind = job["kind"]
        try:
            if kind == "separate":
                self._separate(job, job["_project"], job["_original"], job["_stems"],
                               job.get("_group"), job.get("_split_leaves", False), job["_trim"])
            elif kind == "split-guitar":
                self._separate(job, job["_project"], job["_original"], job["_stems"],
                               None, False, job["_trim"])
            elif kind == "youtube":
                self._youtube(job, job["_root"], job["_url"], job["_fields"])
            elif kind == "setup":
                self._setup(job, job["_stages"])
            elif kind == "export":
                self._export(job, job["_project"], job["_formats"], job["_stems"],
                             job["_prevent_clipping"])
        finally:
            with self.lock:
                if job["finished"] is None:
                    self._finish(job)
                self.active.discard(job_id)
                self.active_jobs.pop(job_id, None)
                if not self.active:
                    self.process = None
            self._job_done.set()

    # ---------------------------------------------------------------- start

    def start(self, identifier: str, preset: str, stems=None, *, group=None,
              split_leaves=False, guitar_split=False, trim=None):
        with self.lock:
            chosen_group = validate_group(group)
            chosen = ['lead', 'rhythm'] if guitar_split else plan_stems(preset, stems, chosen_group)
            project = project_path(self.require_root(), identifier)
            info = describe_project(project)
            if not guitar_split and not info["original"]:
                raise ValueError("This project needs an unambiguous original audio file.")
            if (project / "stems").is_symlink():
                raise ValueError("The stems folder must not be a symlink.")
            if split_leaves and guitar_split:
                raise ValueError("A split-only job cannot also split the guitar.")
            return self._enqueue_separation(identifier, preset, chosen, chosen_group,
                                            split_leaves, guitar_split, info, project, trim)

    def _start_trim(self, project, info, guitar_split, trim):
        if trim is None:
            return None
        if guitar_split:
            guitar = stem_file(project / 'stems', 'guitar')
            return parse_trim(trim, probe_duration(project / 'stems' / guitar), 2.0)
        return parse_trim(trim, probe_duration(project / info["original"]), 1.0)

    def _validate_split_job(self, project, info):
        guitar = stem_file(project / 'stems', 'guitar')
        if guitar not in {item['file'] for item in info['stems']}:
            raise ValueError('Separate the guitar track first.')
        if any(p.is_symlink() or not p.is_file() for p in (project / 'stems').iterdir()):
            raise ValueError('The stems folder must contain regular files only.')
        if any((project / 'stems' / f'{name}{ext}').exists()
               for name in ('lead', 'rhythm') for ext in ('.flac', '.wav')):
            raise ValueError('This project already contains lead or rhythm tracks.')
        return project / 'stems' / guitar

    def _enqueue_separation(self, identifier, preset, chosen, chosen_group, split_leaves,
                            guitar_split, info, project, trim):
        if guitar_split:
            self._validate_split_job(project, info)
        saved_trim = self._start_trim(project, info, guitar_split, trim)
        disk_need = self._separation_disk_need(project, info, guitar_split, split_leaves, saved_trim)
        require_free_space(project, disk_need)
        if not guitar_split:
            # The CLI normalizes the input to a 16-bit WAV in the system temp folder.
            require_free_space(Path(tempfile.gettempdir()), self._seconds(project, info, False, saved_trim)
                               * PCM_BYTES_PER_SECOND)
        job = {"id": uuid.uuid4().hex, "kind": "split-guitar" if guitar_split else "separate",
               "project": identifier, "status": "queued",
               "started": time.time(), "finished": None, "error": None,
               "preset": preset, "stems": chosen, "group": chosen_group or [],
               "guitar_split": guitar_split, "split_leaves": bool(split_leaves),
               "trim": {"start": saved_trim[0], "end": saved_trim[1]} if saved_trim else None,
               "phase": "prepare", "progress": 0, "step_progress": 0, "eta": None,
               "step_eta": None, "step_eta_at": None, "eta_estimated": False,
               "pass_count": 2 if split_leaves else 1, "pass_index": 1,
               "_project": project, "_original": info["original"],
               "_stems": chosen, "_group": chosen_group,
               "_split_leaves": bool(split_leaves), "_trim": saved_trim, "_disk_need": disk_need}
        return self._enqueue(job)

    @staticmethod
    def _seconds(project, info, guitar_split, trim) -> float:
        if trim:
            return trim[1] - trim[0]
        source = project / 'stems' / stem_file(project / 'stems', 'guitar') if guitar_split else project / info["original"]
        return probe_duration(source)

    def _separation_disk_need(self, project, info, guitar_split, split_leaves, trim) -> float:
        """Bytes the project's drive must hold for this run, sized by 16-bit PCM.

        The model writes all six stems even when the plan keeps fewer, and the
        24-bit lead/rhythm pair counts as three. A split-only job also copies the
        current stems folder into its stage."""
        pcm = self._seconds(project, info, guitar_split, trim) * PCM_BYTES_PER_SECOND
        if guitar_split:
            return sum(item["bytes"] for item in info["stems"]) + pcm * 3
        return pcm * (6 + (3 if split_leaves else 0))

    def import_youtube(self, data):
        url = youtube_url(data.get('url'))
        fields = metadata_fields(data)
        with self.lock:
            root = self.require_root()
            if data.get('root') != str(root):
                raise ValueError('The projects folder changed. Reopen YouTube import.')
            if importlib.util.find_spec('yt_dlp') is None:
                raise ValueError('YouTube support is not installed. Click "Install YouTube support" above the link box.')
            if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
                raise ValueError(MISSING_FFMPEG)
            job = {'id': uuid.uuid4().hex, 'kind': 'youtube', 'project': None,
                   'status': 'queued', 'started': time.time(), 'finished': None, 'error': None,
                   'phase': 'download', 'progress': 0, 'step_progress': 0, 'eta': None,
                   'step_eta': None, 'step_eta_at': None, 'eta_estimated': False,
                   'pass_count': 1, 'pass_index': 1,
                   '_root': root, '_url': url, '_fields': fields}
            return self._enqueue(job)

    def setup_status(self):
        stages = [
            {"id": "runtime", "label": "Python runtime & app packages", "size_mb": RUNTIME_SIZE_MB,
             "required": True, "missing": not runtime_ok(), "done": runtime_ok()},
            {"id": "ffmpeg", "label": "FFmpeg (audio conversion)", "size_mb": FFMPEG_SIZE_MB,
             "required": True, "missing": not ffmpeg_ok(), "done": ffmpeg_ok()},
            {"id": "separation", "label": "Separation engine (PyTorch, etc.)", "size_mb": SEPARATION_SIZE_MB,
             "required": True, "missing": not separation_ok(), "done": separation_ok()},
            {"id": "youtube", "label": "YouTube import support (yt-dlp)", "size_mb": YOUTUBE_SIZE_MB,
             "required": False, "missing": not youtube_ok(), "done": youtube_ok()},
        ]
        return {"required": any(s["required"] and s["missing"] for s in stages),
                "stages": stages,
                "total_mb": sum(s["size_mb"] for s in stages if s["missing"])}

    def start_setup(self, stages: list[str]):
        with self.lock:
            allowed = {"ffmpeg", "separation", "youtube"}
            stages = [stage for stage in stages if stage in allowed]
            if not stages:
                raise ValueError("Nothing to set up.")
            job = {"id": uuid.uuid4().hex, "kind": "setup", "project": None,
                   "status": "queued", "started": time.time(), "finished": None, "error": None,
                   "phase": "prepare", "progress": 0, "step_progress": 0, "eta": None,
                   "step_eta": None, "step_eta_at": None, "eta_estimated": False,
                   "pass_count": 1, "pass_index": 1,
                   "stages": stages, "stage": None,
                   "_stages": stages}
            return self._enqueue(job)

    # ---------------------------------------------------------------- workers

    def _setup(self, job, stages: list[str]):
        try:
            run_setup(self, stages)
        except Exception as error:
            with self.lock:
                if job["status"] != "cancelling":
                    job.update(status="failed", error=str(error))
        finally:
            with self.lock:
                self._finish(job)

    def _youtube(self, job, root, url, fields):
        job_id = job["id"]
        try:
            with tempfile.TemporaryDirectory(prefix='.youtube-', dir=root) as temporary:
                work = Path(temporary)
                with self.lock:
                    command = youtube_command(url, work)
                    process = self._launch(job, command, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace',
                        env=dict(os.environ, PYTHONUNBUFFERED='1', PYTHONIOENCODING='utf-8'), start_new_session=True)
                    if process is None:
                        return
                transcript = JobLog(self.log_dir, job, command)
                try:
                    for line in process.stdout:
                        line = line.strip()
                        transcript.write(line)
                        with self.lock:
                            download = YTDLP_PROGRESS.search(line)
                            if download:
                                job['progress'] = max(job['progress'], float(download.group(1)))
                                job['step_progress'] = max(job.get('step_progress') or 0,
                                                            float(download.group(1)))
                                job['eta'] = clock_seconds(download.group(2)) if download.group(2) else None
                                job['eta_at'] = time.time()
                                job['step_eta'] = job['eta']
                                job['step_eta_at'] = job['eta_at']
                                job['eta_estimated'] = False
                            elif line:
                                self._job_logs(job_id).append(line[-2000:])
                    code = process.wait()
                finally:
                    transcript.close(job['status'], job.get('error'))
                    process.stdout.close()
                with self.lock:
                    if job['status'] == 'cancelling':
                        return
                    if code:
                        raise ValueError(f'YouTube download failed (exit {code}). See the download log.')
                    # yt-dlp writes UTF-8; Windows' default cp1252 chokes on non-ASCII titles.
                    info = json.loads((work/'source.info.json').read_text(encoding='utf-8'))
                    defaults = {'title': info.get('track') or info.get('title') or 'YouTube recording',
                                'artist': info.get('artist') or info.get('creator') or '',
                                'album': info.get('album') or '',
                                'year': str(info.get('release_year') or info.get('release_date') or '')[:4]}
                    chosen = {key: fields[key] or str(defaults[key])[:500] for key in defaults}
                    result = import_project(root, work/'source.wav', 'original.wav', chosen,
                                            origin={'provider': 'YouTube', 'url': url})
                    job.update(status='succeeded', project=result['id'])
        except Exception as error:
            with self.lock:
                if job['status'] != 'cancelling':
                    job.update(status='failed', error=str(error))
        finally:
            with self.lock:
                self._finish(job)

    def _separate(self, job, project: Path, original: str, stems: list[str],
                  group=None, split_leaves=False, trim=None):
        job_id = job["id"]
        try:
            # Checked again here: queued jobs ahead of this one may have used the space.
            require_free_space(project, job["_disk_need"])
            with tempfile.TemporaryDirectory(prefix=".separation-", dir=project) as temporary:
                stage = Path(temporary) / "stems"
                command = self._separation_command(job, project, original, stage,
                                                   stems, group, split_leaves, trim)
                # UTF-8 both ways, so non-ASCII song titles and paths survive the pipe on Windows.
                env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", ORT_DISABLE_TELEMETRY="1")
                with self.lock:
                    process = self._launch(job, command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           text=True, encoding="utf-8", errors="replace", env=env, start_new_session=True)
                    if process is None:
                        return
                job_logs = self._job_logs(job_id)
                transcript = JobLog(self.log_dir, job, command)
                try:
                    for line in process.stdout:
                        line = line.strip()
                        transcript.write(line)
                        with self.lock:
                            if line and not self._track_progress(job, line):
                                job_logs.append(line[-2000:])
                    code = process.wait()
                finally:
                    transcript.close(job["status"], job.get("error"))
                    process.stdout.close()
                with self.lock:
                    if job["status"] == "cancelling":
                        return
                if code != 0:
                    raise RuntimeError(f"Separation CLI exited with code {code}. See the process log.")
                self._expect_outputs(stage, stems, group)
                # Publish only a successful run; preserve the old stems on failure.
                with self.lock:
                    if job["status"] == "cancelling":
                        return
                    destination = project / "stems"
                    backup = Path(temporary) / "previous-stems"
                    if destination.exists():
                        destination.rename(backup)
                    try:
                        stage.rename(destination)
                    except BaseException:
                        if backup.exists():
                            backup.rename(destination)
                        raise
                    job.update(status="succeeded", progress=100, step_progress=100, phase="done", eta=0)
        except Exception as error:
            with self.lock:
                if job["status"] != "cancelling":
                    job.update(status="failed", error=str(error))
        finally:
            with self.lock:
                self._finish(job)

    def _separation_command(self, job, project: Path, original: str, stage: Path,
                            stems: list[str], group, split_leaves: bool, trim):
        range_args = ["--start", f"{trim[0]:.3f}", "--end", f"{trim[1]:.3f}"] if trim else []
        if job["kind"] == "split-guitar":
            shutil.copytree(project / 'stems', stage)
            return [sys.executable, '-m', 'unweave', 'split-guitar',
                    '--file', str(stage / stem_file(stage, 'guitar')), '--output', str(stage),
                    '--cache', str(self.cache), *range_args]
        command = [sys.executable, "-m", "unweave", "separate", "--file", str(project / original),
                   "--output", str(stage), "--cache", str(self.cache)]
        if group is not None:
            # An explicit plan may legitimately keep no stem of its own, so send
            # --stems unconditionally (nargs="*") to mean "own files = these".
            command += ["--stems", *stems]
            if group:
                command += ["--group", *group]
        elif stems:
            command += ["--stems", *stems]
        if split_leaves:
            command += ["--split-guitar"]
        return command + range_args

    def _expect_outputs(self, stage: Path, stems: list[str], group):
        """A merged stem must NOT reach the stage: only own files and other.flac do."""
        names = [*stems, *(['other'] if group else [])]
        for name in dict.fromkeys(names):
            path = stage / f"{name}.flac"
            if not path.is_file() or path.stat().st_size <= 44:
                raise RuntimeError(f"CLI did not produce {name}.flac.")

    def start_export(self, identifier: str, formats, stems, *, prevent_clipping=True):
        with self.lock:
            project = project_path(self.require_root(), identifier)
            info = describe_project(project)
            if not info["stems"]:
                raise ValueError("This project has no stems to export.")
            if not isinstance(formats, list) or not formats:
                raise ValueError("Choose at least one export format.")
            chosen_formats = []
            for format_id in formats:
                if not isinstance(format_id, str) or format_id not in FORMATS:
                    raise ValueError("Unknown export format.")
                if format_id not in chosen_formats:
                    chosen_formats.append(format_id)
            if not isinstance(stems, list) or not stems:
                raise ValueError("Choose at least one stem to export.")
            if not isinstance(prevent_clipping, bool):
                raise ValueError("Invalid clipping setting.")
            available = {item["file"] for item in info["stems"]}
            chosen_stems = []
            for name in stems:
                if not isinstance(name, str) or name not in available:
                    raise ValueError("Unknown stem to export.")
                if name not in chosen_stems:
                    chosen_stems.append(name)
            exports = project / "exports"
            if exports.is_symlink() or (exports.exists() and not exports.is_dir()):
                raise ValueError("The exports folder must be a real directory.")
            if not ensure_ffmpeg_on_path():
                raise ValueError(MISSING_FFMPEG)
            # Measured from the stored FLAC stems: PCM formats roughly double them,
            # FLAC stays about the same, lossy formats are a fraction.
            factor = sum(EXPORT_SIZE_FACTOR.get(format_id, 2.0) for format_id in chosen_formats)
            sizes = {item["file"]: item["bytes"] for item in info["stems"]}
            disk_need = sum(sizes[name] for name in chosen_stems) * factor
            require_free_space(project, disk_need)
            job = {"id": uuid.uuid4().hex, "kind": "export", "project": identifier,
                   "status": "queued", "started": time.time(), "finished": None, "error": None,
                   "formats": chosen_formats, "stems": chosen_stems,
                   "prevent_clipping": bool(prevent_clipping),
                   "phase": "prepare", "progress": 0, "step_progress": 0, "eta": None,
                   "step_eta": None, "step_eta_at": None, "eta_estimated": False,
                   "pass_count": 1, "pass_index": 1,
                   "_project": project, "_formats": chosen_formats, "_stems": chosen_stems,
                   "_prevent_clipping": bool(prevent_clipping), "_disk_need": disk_need}
            return self._enqueue(job)

    def _export(self, job, project: Path, formats: list[str], stems: list[str], prevent_clipping: bool):
        job_id = job["id"]
        try:
            require_free_space(project, job["_disk_need"])
            def report(completed, total, label):
                with self.lock:
                    if job["status"] == "cancelling":
                        raise RuntimeError("Export cancelled.")
                    fraction = completed / total if total else 0
                    job["phase"] = "finalize" if completed >= total else "export"
                    job["progress"] = max(2, min(96, 2 + fraction * 93))
                    # The ring is per step: this report is the export step's own 0-100.
                    job["step_progress"] = max(job.get("step_progress") or 0, round(fraction * 100))
                    if fraction > 0.02:
                        job["eta"] = (time.time() - job["started"]) / fraction + 1
                        job["eta_at"] = time.time()
                        job["step_eta"] = job["eta"]
                        job["step_eta_at"] = job["eta_at"]
                        job["eta_estimated"] = False

            def set_process(process):
                with self.lock:
                    if process is not None and job["status"] == "cancelling":
                        stop_process(process)
                    if process is None:
                        self.processes.pop(job_id, None)
                    else:
                        self.processes[job_id] = process

            export_stems(project, stems, formats, prevent_clipping, report, set_process)
            with self.lock:
                if job["status"] != "cancelling":
                    job.update(status="succeeded", progress=100, step_progress=100, phase="done", eta=0)
        except Exception as error:
            with self.lock:
                if job["status"] != "cancelling":
                    job.update(status="failed", error=str(error))
        finally:
            with self.lock:
                self._finish(job)

    # ---------------------------------------------------------------- delete / cancel

    def delete(self, identifier: str, expected_root: str):
        with self.lock:
            root = self.require_root()
            if expected_root != str(root):
                raise ValueError("The projects folder changed. Reopen the deletion dialog.")
            project = project_path(root, identifier)
            active_jobs = list(self.active_jobs.values()) + list(self.queue)
            for job in active_jobs:
                if job.get("project") == identifier:
                    if job["status"] in {"running", "cancelling", "queued"}:
                        raise ValueError("Wait for separation to finish or cancel it before deleting this song.")
            shutil.rmtree(project)
            if self.job and self.job.get("project") == identifier:
                self.job = None
                self.logs.clear()
            return {"ok": True}

    def _process_for(self, job: dict):
        """A job's subprocess. setup_env only sets the `process` alias, which is safe
        to use for setup because setup always runs alone. Caller holds the lock."""
        process = self.processes.get(job["id"])
        if process is None and job["kind"] == "setup":
            process = self.process
        return process

    def cancel(self, job_id: str | None = None):
        processes_to_wait = []
        with self.lock:
            if job_id:
                # Cancel a specific job: either active or waiting in the queue.
                target = None
                if job_id in self.active:
                    target = self.active_jobs.get(job_id)
                    if target:
                        target["status"] = "cancelling"
                        proc = self._process_for(target)
                        if proc:
                            processes_to_wait.append(proc)
                            stop_process(proc)
                else:
                    for index, job in enumerate(self.queue):
                        if job["id"] == job_id:
                            target = self.queue.pop(index)
                            target["status"] = "cancelled"
                            target["finished"] = time.time()
                            break
                    if target is None:
                        raise ValueError("Job not found in queue.")
            else:
                # Cancel all active jobs (used by close).
                if not self.running():
                    return
                for jid in list(self.active):
                    target = self.active_jobs.get(jid)
                    if target:
                        target["status"] = "cancelling"
                    proc = self._process_for(target) if target else None
                    if proc:
                        processes_to_wait.append(proc)
                        stop_process(proc)
        for proc in processes_to_wait:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                stop_process(proc, force=True)

    def pick_folder(self) -> dict:
        """Choose the projects folder with the OS picker and switch to it.

        `native: False` tells the page to fall back to its own folder browser, which
        only happens when the UI runs in a plain browser (`unweave ui`)."""
        if self.window is None or not hasattr(self.window, "pick_folder"):
            return {"native": False}
        with self.lock:
            if self.running() or self.queue:
                raise ValueError("Wait for the current job to finish or cancel it before changing folders.")
            start = str(self.root) if self.root else str(self.default_root)
        # Not under the lock: the dialog waits on the user, and polling must keep going.
        chosen = self.window.pick_folder(start)
        if chosen is None:
            return {"native": True, "cancelled": True}
        self.set_root(chosen)
        return {"native": True, "root": str(self.root)}

    def window_action(self, action: str, data: dict | None = None):
        if action == "pick-folder":
            return self.pick_folder()
        if self.window is None:
            raise ValueError("Not running as a desktop window.")
        data = data or {}
        if action == "minimize":
            self.window.minimize()
        elif action == "toggle-maximize":
            return {"maximized": self.window.toggle_maximize()}
        elif action == "close":
            if self.running() and not (data or {}).get("confirm"):
                return {
                    "confirm": True,
                    "message": "A separation or download is running. Closing will cancel it.",
                }
            self.cancel()  # cancels all active jobs
            # Cancel anything still waiting in the queue so nothing is left mid-run.
            with self.lock:
                for job in list(self.queue):
                    job["status"] = "cancelled"
                    job["finished"] = time.time()
                self.queue.clear()
            self.window.close()
        elif action == "bounds":
            return self.window.bounds()
        elif action == "move":
            self.window.move_to(data.get("x"), data.get("y"))
        elif action == "resize":
            self.window.resize_to(data.get("width"), data.get("height"), data.get("direction", ""))
        else:
            raise ValueError("Unknown window action.")
        return {"ok": True}
