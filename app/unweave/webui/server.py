"""HTTP server and static asset serving for the local web UI."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, unquote, urlsplit

from .library import Library
from ..projects import cover_path, describe_project, import_project, project_path, save_metadata
from ..tools import MISSING_FFMPEG, ensure_ffmpeg_on_path, require_free_space

STATIC = Path(__file__).resolve().parents[1] / "web"

def make_server(library: Library, port: int = 8765):
    token = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            pass

        def respond(self, status, body, content_type="application/json"):
            if not isinstance(body, bytes):
                body = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' blob: data:; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; connect-src 'self'; media-src 'self' blob:; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def json_body(self):
            size = self.body_size(65536)
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError("Expected a JSON object.")
            return data

        def body_size(self, maximum):
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("Chunked requests are not supported.")
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > maximum:
                raise ValueError(f"Request size must be between 1 and {maximum} bytes.")
            return size

        def do_GET(self):
            self.dispatch("GET")

        def do_POST(self):
            self.dispatch("POST")

        def dispatch(self, method):
            try:
                self.connection.settimeout(120)
                host = self.headers.get("Host", "")
                allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
                if host not in allowed or self.headers.get("Origin", f"http://{host}") != f"http://{host}":
                    self.respond(403, {"error": "Local same-origin requests only."})
                    return
                url = urlsplit(self.path)
                path = unquote(url.path)
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                if path.startswith("/api/"):
                    if not secrets.compare_digest(self.headers.get("X-Unweave-Token", ""), token):
                        self.respond(403, {"error": "Reload the UI to authorize this session."})
                        return
                    result = self.api(method, path, query)
                    if result is not None:
                        self.respond(200, result)
                elif method == "GET":
                    name = "index.html" if path == "/" else path.lstrip("/")
                    static_root = STATIC.resolve()
                    file_path = (static_root / name).resolve()
                    if static_root not in file_path.parents or not file_path.is_file():
                        self.respond(404, {"error": "Not found."})
                        return
                    body = file_path.read_bytes()
                    if file_path.name == "index.html":
                        body = body.replace(b"__SESSION_TOKEN__", token.encode())
                    self.respond(200, body, mimetypes.guess_type(str(file_path))[0] or "text/plain")
                else:
                    self.respond(404, {"error": "Not found."})
            except (BrokenPipeError, ConnectionResetError):
                pass
            except (ValueError, OSError, subprocess.SubprocessError) as error:
                self.respond(400, {"error": str(error)})
            except Exception as error:
                print(f"UI request failed: {error}", file=sys.stderr)
                self.respond(500, {"error": "Unexpected server error; see the terminal."})

        def api(self, method, path, query):
            if method == 'POST' and path == '/api/import-youtube':
                return library.import_youtube(self.json_body())
            if method == 'POST' and path == '/api/metadata/search':
                return {'matches': library.lookup.search(self.json_body())}
            if method == 'POST' and path == '/api/metadata/prepare':
                return library.lookup.prepare(self.json_body().get('token'))
            if method == 'GET' and path.startswith('/api/metadata/cover/'):
                item = library.lookup.get(path.rsplit('/', 1)[-1])
                if not item.get('cover'):
                    raise ValueError('Cover not found.')
                self.respond(200, item['cover'], item['cover_type'])
                return None
            if method == "GET" and path == "/api/state":
                return library.state()
            if method == "GET" and path == "/api/updates/status":
                return library.updates_status()
            if method == "POST" and path == "/api/updates/prefs":
                return library.set_updates_prefs(self.json_body())
            if method == "POST" and path == "/api/updates/check":
                data = self.json_body()
                manual = bool(data.get("manual")) if isinstance(data, dict) else False
                return library.check_updates(manual=manual)
            if method == "POST" and path == "/api/setup/start":
                data = self.json_body()
                stages = data.get("stages") or []
                if not isinstance(stages, list) or not all(isinstance(stage, str) for stage in stages):
                    raise ValueError("Expected a list of stage names.")
                return library.start_setup(stages)
            if method == "GET" and path == "/api/folders":
                folder = Path(query.get("path") or str(library.root or Path.home())).expanduser().resolve()
                if not folder.is_dir():
                    raise ValueError("Folder not found.")
                children = [{"name": p.name, "path": str(p.resolve())} for p in folder.iterdir()
                            if p.is_dir() and not p.name.startswith(".")]
                return {"path": str(folder), "parent": str(folder.parent),
                        "folders": sorted(children, key=lambda p: p["name"].casefold())}
            if method == "POST" and path == "/api/library":
                data = self.json_body()
                library.set_root(data.get("path"), create=data.get("create") is True)
                return library.state()
            if method == "POST" and path == "/api/import":
                size = self.body_size(2 * 1024**3)
                # The upload lands in the temp folder, then is copied into the project.
                try:
                    require_free_space(Path(tempfile.gettempdir()), size)
                    if library.root is not None:
                        require_free_space(library.root, size)
                except ValueError:
                    # Read the body off the socket first: answering mid-upload resets the
                    # connection and the webview reports a network error instead of this one.
                    remaining = size
                    while remaining and (chunk := self.rfile.read(min(1024 * 1024, remaining))):
                        remaining -= len(chunk)
                    raise
                with tempfile.TemporaryDirectory(prefix="unweave-upload-") as temporary:
                    upload = Path(temporary) / "upload"
                    with upload.open("wb") as out:
                        remaining = size
                        while remaining:
                            chunk = self.rfile.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise ValueError("Audio upload was interrupted.")
                            out.write(chunk)
                            remaining -= len(chunk)
                    with library.lock:
                        root = library.require_matching_root(query.get("root"))
                        enrichment = library.lookup.get(query['lookup_token']) if query.get('lookup_token') else None
                        return import_project(root, upload, query.get("filename", ""), query, enrichment)
            if method == "POST" and path == "/api/cancel":
                try:
                    data = self.json_body()
                except ValueError:
                    data = {}
                job_id = data.get("job_id") if isinstance(data, dict) else None
                library.cancel(job_id)
                return {"ok": True}
            if path.startswith("/api/window/"):
                action = path[len("/api/window/"):]
                if method == "GET" and action == "bounds":
                    return library.window_action("bounds")
                if method == "POST":
                    return library.window_action(action, self.json_body())
            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[:2] == ["api", "projects"]:
                with library.lock:
                    data = self.json_body() if method == "POST" else query
                    root = library.require_matching_root(data.get("root"))
                    project = project_path(root, parts[2])
                    if method == "POST" and len(parts) == 4 and parts[3] == "metadata":
                        enrichment = library.lookup.get(data['lookup_token']) if data.get('lookup_token') else None
                        return save_metadata(project, data, enrichment)
                    if method == 'GET' and len(parts) == 4 and parts[3] == 'cover':
                        cover = cover_path(project)
                        if not cover:
                            raise ValueError('Cover not found.')
                        self.respond(200, cover.read_bytes(), 'image/png' if cover.suffix == '.png' else 'image/jpeg')
                        return None
                    if method == "POST" and len(parts) == 4 and parts[3] == "separate":
                        return library.start(parts[2], data.get("preset", "vocals"), data.get("stems"),
                                             group=data.get("group"),
                                             split_leaves=bool(data.get("split")),
                                             trim=data.get("trim"))
                    if method == "POST" and len(parts) == 4 and parts[3] == "split-guitar":
                        return library.start(parts[2], 'guitar', guitar_split=True, trim=data.get("trim"))
                    if method == "POST" and len(parts) == 4 and parts[3] == "export":
                        return library.start_export(parts[2], data.get("formats"), data.get("stems"),
                                                    prevent_clipping=data.get("prevent_clipping", True))
                    if method == "POST" and len(parts) == 4 and parts[3] == "reveal":
                        name = data.get("target", "project")
                        targets = {"project": project, "stems": project / "stems",
                                   "exports": project / "exports"}
                        if name not in targets:
                            raise ValueError("Unknown folder target.")
                        target = targets[name]
                        if name in {"stems", "exports"} and (target.is_symlink() or not target.is_dir()):
                            raise ValueError("Folder not found.")
                        if os.name == "nt":
                            os.startfile(target)
                        else:
                            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(target)])
                        return {"ok": True}
                    if method == "POST" and len(parts) == 4 and parts[3] == "delete":
                        return library.delete(parts[2], data.get("root"))
                    audio_route = (method == "GET" and len(parts) == 5 and parts[3] == "audio")
                    original_route = (method == "GET" and len(parts) == 4 and parts[3] == "original")
                    if audio_route:
                        name = parts[4]
                        allowed = {s["file"] for s in describe_project(project)["stems"]}
                        if name not in allowed:
                            raise ValueError("Stem not found.")
                        audio = project / "stems" / name
                        content_type = "audio/flac" if name.endswith(".flac") else "audio/wav"
                        # Open while holding the lock, before a completed job swaps directories.
                        handle = audio.open("rb")
                    elif original_route:
                        # The original file never moves once imported (only stems/ gets
                        # swapped by a job), but opening it here too keeps one lock-then-
                        # stream pattern for every audio route rather than two slightly
                        # different ones.
                        info = describe_project(project)
                        if not info["original"]:
                            raise ValueError("This project has no original recording.")
                        audio = project / info["original"]
                        content_type = mimetypes.guess_type(info["original"])[0] or "application/octet-stream"
                        handle = audio.open("rb")
                if audio_route or original_route:
                    with handle:
                        self.send_response(200)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Length", str(os.fstat(handle.fileno()).st_size))
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.end_headers()
                        shutil.copyfileobj(handle, self.wfile)
                    return None
            raise ValueError("Unknown API route.")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def serve(projects: Path | None, port: int, cache: Path, window=None, config: Path | None = None,
          default_root: Path | None = None):
    if not ensure_ffmpeg_on_path():
        print(MISSING_FFMPEG, file=sys.stderr, flush=True)
    # Callers running from an installed, read-only location (Program Files) must pass
    # config/default_root pointing somewhere actually writable — see ui_entrypoint.py.
    # These relative-path fallbacks only make sense for the `unweave ui` CLI, run
    # from a writable working directory.
    config = config if config is not None else Path(".sound-razor/ui.json")
    default_root = default_root if default_root is not None else Path("output")
    library = Library(projects, config, cache, default_root, window=window)
    server = make_server(library, port)
    print(f"Sound Razor UI: http://127.0.0.1:{server.server_port}", flush=True)
    print("Open that address in your browser. Stop the server with Ctrl+C.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        library.cancel()
        if library._drainer and library._drainer.is_alive():
            library._drainer.join(timeout=8)
        server.server_close()
