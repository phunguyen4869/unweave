# Idea: Standalone Sound Razor Installer

## Goal
Package Sound Razor into a single `.exe` installer so non-technical users can install and run it without knowing Python, venv, or FFmpeg.

## Refined approach: Bootstrap + Native Window + On-Demand Downloads

### 1. Small bootstrap installer (Inno Setup, ~5 MB)
The installer itself is tiny. It does NOT bundle torch, onnxruntime, or the app. Instead it:
- Installs Python 3.11 if missing (via embedded Python embeddable package)
- Installs `uv` and the unweave package with all extras
- Installs FFmpeg (bundled or downloaded)
- Creates Start Menu + Desktop shortcuts
- Downloads model weights on first separation (already automatic)

User experience: double-click `SoundRazor-Setup.exe`, click Next a few times, wait a few minutes while deps download, done.

### 2. Native desktop window (not just a browser URL)
Use **pywebview** — a lightweight Python library that wraps a web frontend in the OS's built-in WebView (EdgeHTML on Windows, WebKit on macOS). Reuses the existing Sound Razor web UI with minimal changes:
- One import + a few lines in `ui.py` to open a native window instead of `webbrowser.open()`
- No Electron/Chromium bundle (saves ~150 MB)
- Feels like a real app: taskbar icon, window controls, no browser chrome

Alternative if Rust is desired: **Tauri** — but that requires rewriting the backend in Rust and the Rust toolchain, which is a much bigger lift for an existing Python codebase.

### 3. Size reduction strategies
| Technique | Savings |
|---|---|
| Don't bundle torch/onnxruntime in installer | ~500 MB → installer is ~5 MB |
| Download deps at install time | Only pay for what user runs |
| Strip debug symbols from PyInstaller build | ~10-20% |
| UPX-compress the bootstrap exe | ~30% on the small installer |
| Lazy-load model weights (already done) | ~424 MB not in installer |

### Build flow (developer)
```sh
# 1. (Optional) Build a frozen single-file exe with PyInstaller for faster first launch
pyinstaller --onefile --windowed unweave/ui_entrypoint.py

# 2. Compile the Inno Setup bootstrap installer
iscc SoundRazor.iss
```

### Deliverable
`SoundRazor-Setup-x64.exe` — a ~5-10 MB bootstrap installer.
First launch downloads ~500 MB of Python deps + FFmpeg + models in the background.
Total disk usage after install: ~600 MB (deps + models + app).

### Files to create
- `unweave/ui.py` — add pywebview wrapper (optional, behind a flag)
- `installer/ SoundRazor.iss` — Inno Setup script
- `installer/ bootstrap.ps1` — download + install logic
- `idea.md` — this file