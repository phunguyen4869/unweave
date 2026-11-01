"""Library root, import, cancel, setup, storage, cleanup, updates, folders."""

from pathlib import Path
import tempfile

from ...projects import import_project
from ...tools import require_free_space


def register(router, library):
    @router.get("/api/state")
    def state(req, query, **_):
        return library.state()

    @router.get("/api/startup")
    def startup(req, query, **_):
        return library.startup_sections()

    @router.get("/api/folders")
    def folders(req, query, **_):
        folder = Path(query.get("path") or str(library.root or Path.home())).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError("Folder not found.")
        children = [{"name": p.name, "path": str(p.resolve())} for p in folder.iterdir()
                    if p.is_dir() and not p.name.startswith(".")]
        return {"path": str(folder), "parent": str(folder.parent),
                "folders": sorted(children, key=lambda p: p["name"].casefold())}

    @router.post("/api/library")
    def set_library(req, query, **_):
        data = req.json_body()
        library.set_root(data.get("path"), create=data.get("create") is True)
        return library.state()

    @router.post("/api/import")
    def import_audio(req, query, **_):
        size = req.body_size(2 * 1024**3)
        # The upload lands in the temp folder, then is copied into the project.
        try:
            require_free_space(Path(tempfile.gettempdir()), size)
            if library.root is not None:
                require_free_space(library.root, size)
        except ValueError:
            # Read the body off the socket first: answering mid-upload resets the
            # connection and the webview reports a network error instead of this one.
            remaining = size
            while remaining and (chunk := req.rfile.read(min(1024 * 1024, remaining))):
                remaining -= len(chunk)
            raise
        with tempfile.TemporaryDirectory(prefix="unweave-upload-") as temporary:
            upload = Path(temporary) / "upload"
            with upload.open("wb") as out:
                remaining = size
                while remaining:
                    chunk = req.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("Audio upload was interrupted.")
                    out.write(chunk)
                    remaining -= len(chunk)
            with library.lock:
                root = library.require_matching_root(query.get("root"))
                enrichment = library.lookup.get(query["lookup_token"]) if query.get("lookup_token") else None
                return import_project(root, upload, query.get("filename", ""), query, enrichment)

    @router.post("/api/import-youtube")
    def import_youtube(req, query, **_):
        return library.import_youtube(req.json_body())

    @router.post("/api/cancel")
    def cancel(req, query, **_):
        try:
            data = req.json_body()
        except ValueError:
            data = {}
        job_id = data.get("job_id") if isinstance(data, dict) else None
        library.cancel(job_id)
        return {"ok": True}

    @router.post("/api/setup/start")
    def setup_start(req, query, **_):
        data = req.json_body()
        stages = data.get("stages") or []
        if not isinstance(stages, list) or not all(isinstance(stage, str) for stage in stages):
            raise ValueError("Expected a list of stage names.")
        return library.start_setup(stages, repair=bool(data.get("repair")))

    @router.get("/api/storage")
    def storage(req, query, **_):
        return library.storage_info()

    @router.post("/api/storage/clear-models")
    def clear_models(req, query, **_):
        req.json_body()  # require a POST body for CSRF-style same-origin habit
        return library.clear_models()

    @router.get("/api/cleanup")
    def cleanup_info(req, query, **_):
        return library.cleanup_info()

    @router.post("/api/cleanup/scan")
    def cleanup_scan(req, query, **_):
        req.json_body()
        return library.run_cleanup_scan()

    @router.post("/api/cleanup/run")
    def cleanup_run(req, query, **_):
        data = req.json_body()
        ids = data.get("ids") if isinstance(data, dict) else None
        if ids is not None and not isinstance(ids, list):
            raise ValueError("ids must be a list of leftover ids.")
        return library.run_cleanup(ids)

    @router.post("/api/cleanup/prefs")
    def cleanup_prefs(req, query, **_):
        return library.set_cleanup_prefs(req.json_body())

    @router.post("/api/cleanup/start")
    def cleanup_start(req, query, **_):
        req.json_body()
        library.start_background_cleanup()
        return {"ok": True}

    @router.get("/api/updates/status")
    def updates_status(req, query, **_):
        return library.updates_status()

    @router.post("/api/updates/prefs")
    def updates_prefs(req, query, **_):
        return library.set_updates_prefs(req.json_body())

    @router.post("/api/updates/check")
    def updates_check(req, query, **_):
        data = req.json_body()
        manual = bool(data.get("manual")) if isinstance(data, dict) else False
        return library.check_updates(manual=manual)
