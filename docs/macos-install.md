# macOS Install Guide

Unweave runs on macOS from the same source as Windows and Linux. There is no
signed `.dmg` and no App Store build — install with a script that creates a
virtual environment, a `unweave` launcher, and an **unsigned** `.app` for the
Dock. Code signing and notarization are intentionally out of scope.

## Quick install

```bash
git clone https://github.com/um1chc5/unweave.git
cd unweave
./installer/install-macos.sh
```

Then run:

```bash
unweave
```

Or open `~/Applications/Unweave.app`. The first time Gatekeeper may block it —
**right-click → Open**, then confirm. That is expected for an unsigned app.

On first launch the app opens its own setup screen and offers to download FFmpeg
and the separation engine (~1.7 GB). Library and Separate stay disabled until you
approve that download. If Homebrew’s `ffmpeg` is already on your `PATH`, the
FFmpeg stage is marked done without downloading.

### Installer options

| Command | Effect |
|---|---|
| `./installer/install-macos.sh` | Install under `~/Library/Application Support/Unweave` |
| `--prefix DIR` | Install somewhere else |
| `--full` | Also download PyTorch/audio-separator now instead of on first launch |
| `--no-deps` | Copy code only; skip `pip install` |
| `--uninstall` | Remove the app, launcher and Dock `.app` |
| `--purge` | Uninstall + remove model cache and settings (keeps songs) |
| `--help` | Show usage |

## Requirements

- **macOS** with Python **3.11 or newer** (python.org installer or Homebrew)
- **`uv`** (recommended) or the standard `venv` module
- ~10 GB free space once models and dependencies are downloaded

No GTK packages are needed. The native window uses pywebview’s Cocoa / WKWebView
backend (PyObjC arrives via pip with `pywebview`).

## Where things go

| Path | Contents |
|---|---|
| `~/Library/Application Support/Unweave` | App copy, `.venv`, settings, models, downloaded FFmpeg |
| `~/.local/bin/unweave` or `/usr/local/bin/unweave` | Launcher script |
| `~/Applications/Unweave.app` | Unsigned Dock wrapper |
| `~/Music/Unweave` | Default projects folder (separated songs) |

## Uninstall

```bash
./installer/install-macos.sh --uninstall
```

This removes the app tree, launcher and Dock `.app`. It keeps settings, models and
songs. For a fuller clean (still keeps songs):

```bash
./installer/install-macos.sh --purge
```

## Browser mode

To open the UI in your default browser instead of the native window:

```bash
UNWEAVE_BROWSER=1 unweave
```

## Troubleshooting

**Gatekeeper says the app can’t be opened.**
Use **right-click → Open** on `Unweave.app`, or launch from the terminal with
`unweave`. The build is unsigned by design.

**`unweave: command not found`.**
Add `~/.local/bin` (or `/usr/local/bin`) to your `PATH`, or run the full path the
installer printed.

**FFmpeg setup fails.**
Install with Homebrew (`brew install ffmpeg`) and reopen the app, or retry the
in-app download (evermeet.cx Intel zips; they also run under Rosetta on Apple
Silicon).

## Notes for maintainers

- Counterpart to `installer/install-linux.sh` and `installer/Unweave.nsis`.
- No notarization, Developer ID, or Sparkle updater.
- `app/unweave/setup_env.py` picks FFmpeg archives per platform (gyan.dev on
  Windows, johnvansickle on Linux, evermeet.cx on macOS).
