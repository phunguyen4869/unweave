"""HTTP server and static asset serving for the local web UI."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from urllib.parse import parse_qs, unquote, urlsplit
from urllib.request import urlopen

from .library import Library
from .routes import build_router
# Re-exported for package-layout smoke tests (handlers live under routes/).
from ..projects import cover_path, describe_project, import_project, project_path, save_metadata  # noqa: F401
from ..tools import MISSING_FFMPEG, ensure_ffmpeg_on_path

STATIC = Path(__file__).resolve().parents[1] / "web"

def make_server(library: Library, port: int = 8765):
    token = secrets.token_urlsafe(32)
    router = build_router(library)

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
                    result = router.handle(method, path, query, self)
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

    server = LocalServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


class LocalServer(ThreadingHTTPServer):
    """Binds its port exclusively. On Windows, SO_REUSEADDR (which HTTPServer sets) lets
    a socket bind a port another program already listens on, so the window could end
    up talking to that program; the exclusive flag makes the bind fail instead."""
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


# Ports tried after the requested one before asking the OS for any free port. The page
# keeps its theme and language in localStorage, which is per port, so staying on the
# requested port whenever it is free keeps those settings.
PORT_ATTEMPTS = 20


def bind_server(library: Library, port: int):
    """make_server() on `port`, or the next free port when another program holds it."""
    error = None
    for candidate in (*range(port, port + PORT_ATTEMPTS), 0):
        try:
            return make_server(library, candidate)
        except OSError as caught:
            error = caught
    raise error


def running_unweave(port: int, timeout: float = 2.0) -> bool:
    """Whether the server on `port` is Unweave's own, from another launch of the app."""
    try:
        with urlopen(f"http://127.0.0.1:{port}/", timeout=timeout) as response:
            return response.status == 200 and b"<title>Unweave</title>" in response.read(4096)
    except (OSError, ValueError):
        return False


def serve(projects: Path | None, port: int, cache: Path, window=None, config: Path | None = None,
          default_root: Path | None = None, on_ready=None):
    if not ensure_ffmpeg_on_path():
        print(MISSING_FFMPEG, file=sys.stderr, flush=True)
    # Callers running from an installed, read-only location (Program Files) must pass
    # config/default_root pointing somewhere actually writable — see ui_entrypoint.py.
    # These relative-path fallbacks only make sense for the `unweave ui` CLI, run
    # from a writable working directory.
    config = config if config is not None else Path(".sound-razor/ui.json")
    default_root = default_root if default_root is not None else Path("output")
    library = Library(projects, config, cache, default_root, window=window)
    server = bind_server(library, port)
    if server.server_port != port:
        print(f"Port {port} is in use by another program; using {server.server_port}.", flush=True)
    print(f"Unweave UI: http://127.0.0.1:{server.server_port}", flush=True)
    if on_ready is not None:
        # The socket is already listening, so the window can connect from here on.
        on_ready(server.server_port)
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
