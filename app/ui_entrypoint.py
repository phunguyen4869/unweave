"""Unweave - Native app using pywebview."""
import sys
import os
import threading
import time
import webbrowser
from pathlib import Path

try:
    import webview
    from webview.window import FixPoint
except ImportError:
    webview = None
    FixPoint = None

MIN_WIDTH, MIN_HEIGHT = 1100, 700


def known_folder(guid: str, fallback: Path) -> Path:
    """Ask Windows for a Known Folder's real path via the Shell API, rather than
    assuming %USERPROFILE%\\Documents etc. — those are wrong (and still "exist" as
    plain, writable, but *not the folder the user actually sees*) once OneDrive's
    "Backup your folders" feature redirects Documents/Desktop into
    %USERPROFILE%\\OneDrive\\..., which it does by default on many Windows setups."""
    if os.name != "nt":
        return fallback
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_byte * 8)]

    folder_id = GUID()
    path_ptr = ctypes.c_wchar_p()
    try:
        if ctypes.windll.ole32.CLSIDFromString(guid, ctypes.byref(folder_id)) != 0:
            return fallback
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(folder_id), 0, 0, ctypes.byref(path_ptr)) != 0:
            return fallback
        return Path(path_ptr.value)
    except Exception:
        return fallback
    finally:
        if path_ptr.value:
            ctypes.windll.ole32.CoTaskMemFree(path_ptr)


def writable_dirs():
    """Where this app keeps its own data when it may be installed somewhere read-only
    (Program Files needs admin rights to write to — a plain double-click shortcut never
    has them, so writing config/models/output there crashes the app before its window
    even opens, silently, since pythonw.exe shows no console for the traceback).

    Background data (config, the multi-hundred-MB model cache) goes under the standard
    per-user app-data folder; the default separated-song output folder goes somewhere
    the user would actually look for it — the *real*, possibly OneDrive-redirected,
    Documents folder, not a guessed %USERPROFILE%\\Documents that may silently diverge
    from what Explorer actually shows the user as "Documents".
    """
    from unweave.tools import APP_NAME, app_data_dir as app_data, migrate_legacy_data_dir
    migrate_legacy_data_dir()
    app_data_dir = app_data()
    documents = known_folder("{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",  # FOLDERID_Documents
                              Path(os.environ.get("USERPROFILE") or Path.home()) / "Documents")
    return {
        "config": app_data_dir / "ui.json",
        "cache": app_data_dir / "models",
        "default_root": documents / APP_NAME,
    }

# Which corner/edge stays put while the opposite one follows the mouse, keyed by the
# resize handle's compass direction (see resize_to below).
FIX_POINTS = None if FixPoint is None else {
    "n": FixPoint.SOUTH | FixPoint.WEST, "s": FixPoint.NORTH | FixPoint.WEST,
    "e": FixPoint.NORTH | FixPoint.WEST, "w": FixPoint.NORTH | FixPoint.EAST,
    "ne": FixPoint.SOUTH | FixPoint.WEST, "nw": FixPoint.SOUTH | FixPoint.EAST,
    "se": FixPoint.NORTH | FixPoint.WEST, "sw": FixPoint.NORTH | FixPoint.EAST,
}


class WindowControls:
    """Window controls for the custom title bar and its invisible resize edges.

    Reached over the app's own HTTP API (POST/GET /api/window/<action>), not pywebview's
    JS bridge: in practice window.pywebview never materializes in the page here, so the
    bridge is unusable. Calling pywebview's window methods from this (non-GUI) server
    thread is the officially supported cross-thread usage pattern.

    Move and resize are driven by continuous mousemove from the page (see app.js), not
    the classic WM_SYSCOMMAND/HTCAPTION "let the OS drag it" trick: that trick is well
    known to be unreliable with Chromium-based webviews (WebView2's own mouse capture
    competes with the OS's), and that's exactly what we saw here — it simply never moved
    the window. Explicit move()/resize() calls on every frame sidestep that entirely.
    """

    def __init__(self):
        self._window = None

    def attach(self, window):
        self._window = window

    def minimize(self):
        self._window.minimize()

    def is_maximized(self):
        # Ask the real native window rather than tracking our own flag: two toggle
        # calls close together (a fast double-click, or two browser tabs) would
        # otherwise race and leave a hand-rolled flag out of sync with reality.
        if self._window is None or self._window.native is None:
            return False
        return str(self._window.native.WindowState) == "Maximized"

    def toggle_maximize(self):
        self._window.restore() if self.is_maximized() else self._window.maximize()
        return self.is_maximized()

    def close(self):
        self._window.destroy()

    def pick_folder(self, start: str | None = None) -> str | None:
        """The OS folder picker; blocks this server thread until the user answers."""
        dialog = webview.FileDialog.FOLDER if hasattr(webview, "FileDialog") else webview.FOLDER_DIALOG
        directory = start if start and Path(start).is_dir() else ""
        chosen = self._window.create_file_dialog(dialog, directory=directory)
        if not chosen:
            return None
        return chosen if isinstance(chosen, str) else chosen[0]

    def bounds(self):
        w = self._window
        return {"x": w.x, "y": w.y, "width": w.width, "height": w.height}

    def move_to(self, x, y):
        try:
            self._window.move(int(x), int(y))
        except (TypeError, ValueError):
            raise ValueError("move needs numeric x/y.") from None

    def resize_to(self, width, height, direction):
        try:
            width, height = int(width), int(height)
        except (TypeError, ValueError):
            raise ValueError("resize needs numeric width/height.") from None
        fix = FIX_POINTS.get(direction, FixPoint.NORTH | FixPoint.WEST)
        self._window.resize(max(MIN_WIDTH, width), max(MIN_HEIGHT, height), fix)


def app_icon() -> str | None:
    """The app's own icon for the window and its taskbar button. Without one, pywebview's
    Windows backend takes python.exe's icon, since python.exe owns the window. The
    installer puts icon.ico next to this file; a checkout has it in ../assets."""
    here = Path(__file__).resolve().parent
    for path in (here / "icon.ico", here.parent / "assets" / "icon.ico"):
        if path.is_file():
            return str(path)
    return None


def main():
    host = "127.0.0.1"
    port = 8765

    # Use the CLI to start the UI server
    from unweave.webui import serve
    from pathlib import Path

    # Created before the window exists and handed straight to serve(): it's only ever
    # *used* once a request reaches it, which can't happen until the window (created
    # further down) is visible and attach() below has already run.
    controls = WindowControls() if webview is not None else None

    dirs = writable_dirs()

    def run_server():
        serve(None, port, dirs["cache"], window=controls, config=dirs["config"], default_root=dirs["default_root"])

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Give server time to start
    time.sleep(2)

    url = f"http://{host}:{port}"

    if webview is not None:
        # ?native=1 tells the page (synchronously, no race) to show its own title bar
        # immediately; its buttons call back through controls above via the HTTP API.
        window = webview.create_window(
            title="Unweave",
            url=f"{url}/?native=1",
            width=1400,
            height=900,
            min_size=(MIN_WIDTH, MIN_HEIGHT),
            resizable=True,
            frameless=True,
            # pywebview's easy_drag moves a frameless window on a mousedown anywhere, so
            # dragging a volume slider or trim handle dragged the whole app. Our own title
            # bar (.titlebar-drag in window.js) is the only drag area.
            easy_drag=False,
            background_color="#0b0c0f",
        )
        controls.attach(window)
        # Lets Chrome DevTools attach to the real window for troubleshooting (distinct
        # from debug=True below, which would also add a right-click "Inspect" menu).
        webview.settings["REMOTE_DEBUGGING_PORT"] = 9223
        webview.start(debug=False, icon=app_icon())
    else:
        webbrowser.open(url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
