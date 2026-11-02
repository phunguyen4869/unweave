# Desktop App — Packaging (`um1chc5/unweave`)

## Goal

Ship Unweave as an installable desktop app so non-technical users can run it without
touching Python, a venv, or PATH. The installer stays small: heavy dependencies are
fetched by the app itself, with the user's consent, on first launch.

## Pieces

### 1. Windows installer (`installer/Unweave.nsis`, NSIS)

Built with NSIS, not Inno Setup. It deliberately does **no** network access: it copies the
app, a prebuilt embedded Python runtime, writes shortcuts and an uninstaller.

- Ships embeddable Python 3.11.9 (`installer/embedded/runtime/`, prebuilt with pip and
  pywebview). `unweave.pth` puts the package on its path.
- Runs `makensis launcher.nsi` first, producing `Unweave.exe` — the console-less launcher
  that starts `ui_entrypoint.py` and keeps a log at `%LOCALAPPDATA%\Unweave\launch.log`.
- Output: `dist/Unweave-Setup-x64.exe`.
- Start Menu and Desktop shortcuts, plus a proper uninstaller with registry entries.

Build:

```sh
cd installer
makensis Unweave.nsis
```

Why no heavy deps inside: bundling PyTorch/audio-separator would push the download to
~2 GB. Beyond size, it lets a user pick only what they need (for example skipping YouTube
support).

### 2. First-run setup (inside the app)

`app/unweave/setup_env.py` detects what is missing and installs it on request, behind
an explicit consent screen:

- `runtime_ok()`, `ffmpeg_ok()`, `separation_ok()`, `youtube_ok()` probe each stage.
- `STAGE_ORDER` is `ffmpeg`, `separation`, `youtube`; stage progress is reported on the
  shared job band (0-90 across missing stages, last 10 for verification).
- Models (~425 MB) download lazily on first separation, not during setup.

### 3. Native window (pywebview)

The launcher opens the local UI in the OS WebView instead of a browser tab:

- No Electron/Chromium bundle (saves roughly 150 MB and an entire update channel).
- Real app behaviour: taskbar entry, window controls, no browser chrome.
- The custom title bar's window buttons reach the window over `/api/window/*`, not the
  pywebview JS bridge, which proved unreliable in practice.

**Why not Tauri?** It would mean rewriting the backend in Rust. pywebview reuses the
existing web UI and Python server unchanged.

### 4. Linux (`installer/install-linux.sh`)

The Linux counterpart to `bootstrap.ps1` + `Unweave.nsis`. There is no portable embedded
interpreter for Linux, so the script builds a venv with `uv`, installs the app, and writes
a launcher plus a `.desktop` entry. `UNWEAVE_BROWSER=1` opens the UI in a system browser
(workaround for silent WebKitGTK Web Audio).

```sh
./install-linux.sh                 # install to ~/.local/share/unweave
./install-linux.sh --prefix DIR    # elsewhere
./install-linux.sh --full          # also install PyTorch/audio-separator now
./install-linux.sh --no-deps       # reinstall code only
./install-linux.sh --uninstall     # remove the app, keep models and songs
```

### 5. macOS (`installer/install-macos.sh`)

Same shape as the Linux script: venv + launcher under
`~/Library/Application Support/Unweave`, plus an **unsigned** `~/Applications/Unweave.app`.
No Developer ID signing or notarization. See [macos-install.md](macos-install.md).

```sh
./install-macos.sh                 # default Application Support prefix
./install-macos.sh --full          # also install PyTorch/audio-separator now
./install-macos.sh --uninstall     # remove app + launcher; keep models and songs
```

### 6. Windows bootstrap (`installer/bootstrap.ps1`)

A scripted alternative for users who cannot run the NSIS installer.

## Sizing

| Component | Where it comes from | Size |
|---|---|---|
| Installer | NSIS, app + embedded runtime | ~30-40 MB |
| PyTorch + audio-separator | first-run setup | ~1.6 GB |
| FFmpeg | first-run setup | ~100 MB |
| Model weights | first separation, lazy | ~425 MB |

## Updates

The app does not auto-install. After first-run setup is usable, it may ask permission to
look up the latest GitHub Release (throttled, no account). About → Check for updates
always works. Details: [10 — In-app update check](specs/10-updates.md).

## Technical risks

- The embedded runtime must find the package: `python311._pth` needs the `..` entry, or
  `import unweave` fails at launch. This broke every installed copy once and is only
  caught by running the real installed exe, not a dev venv.
- pywebview on Windows needs the Edge WebView2 runtime, which may need bundling or
  downloading on older systems.
- NSIS must cope with long paths and Windows filename restrictions.
- Model and dependency downloads can be slow on poor connections; the setup screen shows
  per-stage progress for this reason.
- The frozen exe must locate FFmpeg at runtime, since it is installed outside the app
  directory.
