"""Updates, leftover cleanup, and storage settings for the local UI."""

import shutil
import threading
import time
from pathlib import Path

from ..projects import list_projects, project_path
from ..tools import app_version
from ..updates import (ASK_AGAIN_S, CHECK_INTERVAL_S, RELEASES_LATEST_PAGE, fetch_latest_release,
                       is_newer, normalize_tag)
from ..fsutil import dir_bytes, is_link_like
from .. import cleanup as leftovers

APP_VERSION = app_version()
# Kept for callers/tests that still import the name; the scanner owns the real list.
STALE_STAGING_MAX_AGE_HOURS = leftovers.AGE_HOURS


class SettingsMixin:
    """Prefs, cleanup, and disk usage. Mixed into Library."""

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

    def _cleanup_prefs(self) -> dict:
        section = self._load_config().get("cleanup")
        if not isinstance(section, dict):
            section = {}
        return {"auto": bool(section.get("auto")), "dont_ask": bool(section.get("dont_ask"))}

    def _write_cleanup_prefs(self, prefs: dict):
        data = self._load_config()
        data["cleanup"] = prefs
        self._save_config(data)

    def set_cleanup_prefs(self, data: dict | None) -> dict:
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        with self.lock:
            prefs = self._cleanup_prefs()
            if "auto" in data:
                prefs["auto"] = bool(data["auto"])
            if "dont_ask" in data:
                prefs["dont_ask"] = bool(data["dont_ask"])
            self._write_cleanup_prefs(prefs)
            return prefs

    def cleanup_info(self) -> dict:
        with self.lock:
            scan = dict(self._cleanup_scan)
            prefs = self._cleanup_prefs()
        return {
            "items": scan.get("items") or [],
            "bytes": scan.get("bytes") or 0,
            "count": scan.get("count") or 0,
            "scanned_at": scan.get("scanned_at"),
            "truncated": bool(scan.get("truncated")),
            "prefs": prefs,
        }

    def _snapshot_cleanup_roots(self):
        with self.lock:
            return self.root, self.cache, self._jobs_busy()

    def run_cleanup_scan(self, *, min_age_hours: float | None = None) -> dict:
        """Scan now (foreground). Used by Settings and tests."""
        root, cache, busy = self._snapshot_cleanup_roots()
        result = leftovers.scan(
            projects_root=root, model_cache=cache,
            min_age_hours=leftovers.AGE_HOURS if min_age_hours is None else min_age_hours,
            jobs_busy=busy,
        )
        with self.lock:
            self._cleanup_scan = result
        return self.cleanup_info()

    def run_cleanup(self, ids=None, *, min_age_hours: float | None = None) -> dict:
        root, cache, busy = self._snapshot_cleanup_roots()
        with self.lock:
            previous = dict(self._cleanup_scan)
        cleaned = leftovers.clean(
            ids, previous=previous, projects_root=root, model_cache=cache,
            min_age_hours=leftovers.AGE_HOURS if min_age_hours is None else min_age_hours,
            jobs_busy=busy,
        )
        # Refresh the cached scan after a clean.
        self.run_cleanup_scan(min_age_hours=min_age_hours)
        return cleaned

    def start_background_cleanup(self, *, apply_silent: bool = True) -> None:
        """Kick off a background scan after the UI is usable; apply the silent rule."""
        with self._cleanup_lock:
            if self._cleanup_thread and self._cleanup_thread.is_alive():
                return

            def worker():
                try:
                    info = self.run_cleanup_scan()
                    prefs = info["prefs"]
                    decision = leftovers.sections_for_startup(
                        updates_should_prompt=False,
                        cleanup_bytes=info["bytes"],
                        cleanup_auto=prefs["auto"],
                        cleanup_dont_ask=prefs["dont_ask"],
                    )
                    if apply_silent and decision["silent_cleanup"] and info["count"]:
                        cleaned = self.run_cleanup()
                        freed = cleaned.get("freed_bytes") or 0
                        # Under 50 MB: silent with no toast. Auto-clean of large
                        # leftovers: silent delete + "Freed X" notice.
                        if freed and info["bytes"] >= leftovers.SILENT_BYTES and prefs["auto"]:
                            with self.lock:
                                self._cleanup_notice = {"freed_bytes": freed}
                except Exception:
                    pass

            self._cleanup_thread = threading.Thread(target=worker, daemon=True, name="unweave-cleanup")
            self._cleanup_thread.start()

    def startup_sections(self, *, ensure_scan: bool = True) -> dict:
        """Which sections the combined startup dialog should show right now."""
        if ensure_scan:
            with self.lock:
                scanned = self._cleanup_scan.get("scanned_at")
            if scanned is None:
                info = self.run_cleanup_scan()
                prefs = info["prefs"]
                decision = leftovers.sections_for_startup(
                    updates_should_prompt=False,
                    cleanup_bytes=info["bytes"],
                    cleanup_auto=prefs["auto"],
                    cleanup_dont_ask=prefs["dont_ask"],
                )
                if decision["silent_cleanup"] and info["count"]:
                    cleaned = self.run_cleanup()
                    freed = cleaned.get("freed_bytes") or 0
                    if freed and info["bytes"] >= leftovers.SILENT_BYTES and prefs["auto"]:
                        with self.lock:
                            self._cleanup_notice = {"freed_bytes": freed}
        updates = self.updates_status()
        cleanup = self.cleanup_info()
        prefs = cleanup["prefs"]
        decision = leftovers.sections_for_startup(
            updates_should_prompt=bool(updates.get("should_prompt")),
            cleanup_bytes=cleanup["bytes"],
            cleanup_auto=prefs["auto"],
            cleanup_dont_ask=prefs["dont_ask"],
        )
        return {
            **decision,
            "updates": updates,
            "cleanup": cleanup,
            "should_auto_check": bool(updates.get("should_auto_check")),
        }

    def sweep_stale_staging(self, max_age_hours: int | None = None) -> list[str]:
        """Remove stale staging / model-download leftovers via the shared scanner.

        Same behaviour as before for projects-root staging, plus per-project and
        model-cache leftovers the old walk never reached. Temp leftovers are left
        for the background clean-up (spec 13) so the user can be asked about large ones.
        """
        max_age_hours = STALE_STAGING_MAX_AGE_HOURS if max_age_hours is None else max_age_hours
        with self.lock:
            busy = self._jobs_busy()
            root = self.root
            cache = self.cache
        # Snapshot only; size/delete without the lock. Skip system temp — large
        # leftovers there are offered in the startup dialog (spec 13).
        result = leftovers.scan(
            projects_root=root, model_cache=cache,
            min_age_hours=max_age_hours, jobs_busy=busy, include_temp=False,
        )
        staging = [item for item in result["items"] if item["group"] in {"interrupted", "downloads"}]
        if not staging:
            return []
        cleaned = leftovers.clean(
            [item["id"] for item in staging], previous={"items": staging},
            projects_root=root, model_cache=cache,
            min_age_hours=max_age_hours, jobs_busy=busy,
        )
        by_id = {item["id"]: item["path"] for item in staging}
        return [by_id[i] for i in cleaned["removed"] if i in by_id]

    def storage_info(self) -> dict:
        """Model-cache and per-project sizes for the settings Storage section.

        Snapshot root/cache/project ids under the lock, then size on disk without
        holding it so /api/state polling and job progress stay responsive.
        """
        with self.lock:
            cache = self.cache
            root = self.root
            metas = []
            if root is not None and root.is_dir() and not is_link_like(root):
                for info in list_projects(root):
                    metas.append({
                        "id": info["id"],
                        "title": info.get("title") or info["id"],
                    })
            root_snapshot = root
            cache_snapshot = cache

        projects = []
        projects_bytes = 0
        if root_snapshot is not None and root_snapshot.is_dir() and not is_link_like(root_snapshot):
            for meta in metas:
                project = project_path(root_snapshot, meta["id"])
                if is_link_like(project) or not project.is_dir():
                    continue
                total = dir_bytes(project)
                exports = project / "exports"
                exports_bytes = (dir_bytes(exports)
                                 if exports.is_dir() and not is_link_like(exports) else 0)
                projects_bytes += total
                projects.append({
                    "id": meta["id"],
                    "title": meta["title"],
                    "bytes": total,
                    "exports_bytes": exports_bytes,
                })
        return {
            "models_path": str(cache_snapshot),
            "models_bytes": dir_bytes(cache_snapshot),
            "projects_root": str(root_snapshot) if root_snapshot else None,
            "projects_bytes": projects_bytes,
            "projects": projects,
        }

    def clear_models(self) -> dict:
        """Delete the model cache. Refuses while any job is running or queued."""
        with self.lock:
            if self._jobs_busy():
                raise ValueError("Wait for the current job to finish or cancel it before clearing models.")
            cache = self.cache
            if cache.is_symlink():
                raise ValueError("The model cache path is not a real folder.")
            freed = 0
            if cache.is_dir():
                freed = dir_bytes(cache)
                for entry in list(cache.iterdir()):
                    if entry.is_symlink():
                        continue
                    if entry.is_dir():
                        shutil.rmtree(entry)
                    elif entry.is_file():
                        entry.unlink()
            cache.mkdir(parents=True, exist_ok=True)
            return {"ok": True, "freed_bytes": freed, "models_bytes": dir_bytes(cache)}

