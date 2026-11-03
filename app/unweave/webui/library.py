"""Project library façade: root, state, window chrome; jobs/settings via mixins."""

from collections import deque
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from ..diagnostics import (build_diagnostics_text, host_arch, host_platform_name,
                           host_python)
from ..projects import atomic_json, list_projects
from ..projects.metadata import MetadataLookup
from ..tools import env_first
from ..fsutil import dir_bytes, is_link_like  # re-exported for tests that patch library.dir_bytes
from .plans import CUSTOM_STEMS, PLAN_STEMS, plan_stems, selection_stems, validate_group
from .progress import FINALIZE_FUDGE, GUITAR_TIME_RATIO, SEPARATE_RANGE
from .queue import (APP_VERSION, EXPORT_SIZE_FACTOR, JOB_LOG_KEEP, JobLog, JobQueueMixin,
                    prune_job_logs, public_job)
from .settings import STALE_STAGING_MAX_AGE_HOURS, SettingsMixin

__all__ = [
    "CUSTOM_STEMS", "PLAN_STEMS", "EXPORT_SIZE_FACTOR", "STALE_STAGING_MAX_AGE_HOURS",
    "FINALIZE_FUDGE", "GUITAR_TIME_RATIO", "SEPARATE_RANGE", "APP_VERSION", "JOB_LOG_KEEP",
    "JobLog", "Library", "plan_stems", "prune_job_logs", "public_job",
    "selection_stems", "validate_group",
]


class Library(JobQueueMixin, SettingsMixin):
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
        self._cleanup_scan = {"items": [], "bytes": 0, "count": 0, "scanned_at": None}
        self._cleanup_notice = None  # {freed_bytes} for a one-shot UI toast after silent clean
        self._cleanup_thread = None
        self._cleanup_lock = threading.Lock()
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

    def require_matching_root(self, expected_root):
        root = self.require_root()
        if expected_root != str(root):
            raise ValueError("The projects folder changed. Refresh the library and reopen this action.")
        return root

    def state(self):
        """Snapshot queue fields under the lock; list projects outside it.

        `list_projects()` walks the library on disk. Holding the job lock across
        that scan made /api/state compete with progress-line updates.
        """
        with self.lock:
            root = self.root
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
            # notices still surface after workers exit. Include logs so first-run
            # setup can show a collapsible transcript without hunting the jobs list.
            job_shim = public_job(self.job) if self.job else None
            if job_shim is not None:
                job_shim["logs"] = list(self._job_logs(self.job["id"]))
            notice = self._cleanup_notice
            self._cleanup_notice = None
            cleanup = {
                "bytes": self._cleanup_scan.get("bytes") or 0,
                "count": self._cleanup_scan.get("count") or 0,
                "scanned_at": self._cleanup_scan.get("scanned_at"),
                "prefs": self._cleanup_prefs(),
                "notice": notice,
            }
            payload = {"root": str(root) if root else None, "default_root": str(self.default_root),
                       "jobs": jobs,
                       "active_job": next(iter(self.active)) if self.active else None,
                       "active_jobs": [jid for jid in self.active],
                       "max_concurrent_jobs": self.max_concurrent_jobs,
                       "job": job_shim,
                       "finished_jobs": [public_job(job) for job in self.finished_jobs],
                       "cleanup": cleanup,
                       "version": APP_VERSION, "now": time.time(),
                       "platform": (
                           "windows" if sys.platform == "win32"
                           else "darwin" if sys.platform == "darwin"
                           else "linux" if sys.platform.startswith("linux")
                           else sys.platform
                       )}
        payload["projects"] = list_projects(root) if root else []
        payload["setup"] = self.setup_status()
        return payload

    def _diagnostics_job(self, job_id: str | None = None) -> tuple[dict | None, list[str]]:
        """Pick a job + its in-memory log lines for the diagnostics bundle."""
        if job_id:
            job = self.active_jobs.get(job_id)
            if job is None:
                for queued in self.queue:
                    if queued.get("id") == job_id:
                        job = queued
                        break
            if job is None:
                for finished in reversed(self.finished_jobs):
                    if finished.get("id") == job_id:
                        job = finished
                        break
            if job is None and self.job and self.job.get("id") == job_id:
                job = self.job
            if job is not None:
                return job, list(self._job_logs(job["id"]))
            return None, []

        # Prefer the newest failed finished job, then any active job, then the shim.
        for finished in reversed(self.finished_jobs):
            if finished.get("status") == "failed":
                return finished, list(self._job_logs(finished["id"]))
        for job_id in self.active:
            job = self.active_jobs.get(job_id)
            if job is not None:
                return job, list(self._job_logs(job_id))
        if self.job is not None:
            return self.job, list(self._job_logs(self.job["id"]))
        if self.finished_jobs:
            job = self.finished_jobs[-1]
            return job, list(self._job_logs(job["id"]))
        return None, []

    def diagnostics(self, job_id: str | None = None) -> dict:
        """Plain-text diagnostics for clipboard paste (spec 15). No network upload."""
        with self.lock:
            job, log_lines = self._diagnostics_job(job_id)
            root = self.root
            public = public_job(job) if job else None
        setup = self.setup_status()
        text = build_diagnostics_text(
            version=APP_VERSION,
            platform_name=host_platform_name(),
            arch=host_arch(),
            python_version=host_python(),
            setup_stages=setup.get("stages"),
            job=public,
            log_lines=log_lines,
            projects_root=root,
        )
        return {"text": text}

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
        elif action == "open-external":
            # Works even when window controls exist: used for Linux “Open in browser”.
            url = (data or {}).get("url")
            opener = getattr(self.window, "open_external", None)
            if callable(opener):
                opener(url)
            else:
                import webbrowser
                if not isinstance(url, str) or not url.startswith(("http://", "https://")):
                    raise ValueError("open-external needs an http(s) URL.")
                if not webbrowser.open(url):
                    raise ValueError("Could not open the system browser.")
        else:
            raise ValueError("Unknown window action.")
        return {"ok": True}

