# Linux Install Guide

Unweave runs on Linux from the same source as the Windows build. There
is no `.exe` and no installer wizard — Linux installs with a script that sets up a
virtual environment and a desktop entry, the same way the Windows
`bootstrap.ps1` sets one up on Windows.

## Quick install

```bash
git clone https://github.com/um1chc5/unweave.git
cd unweave
./installer/install-linux.sh
```

Then start it from your applications menu, or run:

```bash
unweave
```

On first launch the app opens its own setup screen and offers to download FFmpeg
and the separation engine (~1.7 GB) — exactly like the Windows build. Library and
Separate stay disabled until you approve that download.

### Installer options

| Command | Effect |
|---|---|
| `./installer/install-linux.sh` | Install to `~/.local/share/unweave` (default) |
| `--prefix DIR` | Install somewhere else |
| `--full` | Also download PyTorch/audio-separator now instead of on first launch |
| `--no-deps` | Copy code only; skip `pip install` (fast re-install of app changes) |
| `--uninstall` | Remove the app, launcher and menu entry |
| `--help` | Show usage |

## Requirements

- **Python 3.11 or newer**
- **`uv`** (recommended) or the standard `venv` module — the script falls back to
  `python -m venv` if `uv` is missing
- **GTK 3 + WebKit2** for the native window (see below)
- ~10 GB free space once models and dependencies are downloaded

### Native window prerequisites

The app opens in a native window via [pywebview](https://pywebview.flowrl.com/),
which on Linux uses GTK 3 and WebKit2 through `gi`. These are system packages that
**cannot** be installed with `pip`, so install them with your package manager:

```bash
# Debian / Ubuntu / Linux Mint
sudo apt install python3-gi gir1.2-gtk-3.0 gir1.2-webkit2-4.1

# Fedora
sudo dnf install python3-gobject gtk3 webkit2gtk4.1

# Arch / Manjaro
sudo pacman -S python-gobject gtk3 webkit2gtk-4.1
```

> **On older distros** (Debian 11, Ubuntu 20.04) the WebKit package is named
> `gir1.2-webkit2-4.0` instead of `-4.1`; pywebview supports both.

If these packages are missing the app still runs — it just falls back to opening
in your default browser. To force that deliberately (also the workaround for
silent WebKitGTK playback):

```bash
UNWEAVE_BROWSER=1 unweave
```

`UNWEAVE_BROWSER` is honored by `ui_entrypoint.py`. In the native window on Linux
the app also shows a dismissible banner with an **Open in browser** link.

## Where things go

| Path | Contents |
|---|---|
| `~/.local/share/unweave` | The app itself, its `.venv`, settings, models, FFmpeg |
| `~/.local/bin/unweave` | Launcher script |
| `~/.local/share/applications/unweave.desktop` | Menu entry |
| `~/.local/share/icons/unweave.png` | Icon |
| `~/.local/share/unweave/ui.json` | Your last-used projects folder |
| `~/.local/share/unweave/models` | Downloaded AI models (~455 MB) |
| `~/Music/Unweave` | Your separated songs (the default projects folder) |

FFmpeg, once downloaded by the first-run setup, lands next to the app in
`~/.local/share/unweave/`.

## Uninstall

```bash
./installer/install-linux.sh --uninstall
```

This removes the app, the launcher and the menu entry. It deliberately **keeps**
your models, settings and separated songs — delete these by hand for a clean
slate:

```bash
rm -rf ~/.local/share/unweave ~/Music/"Unweave"
```

## Troubleshooting

**The app opens in a browser instead of a window.**
The GTK/WebKit system packages above are missing, or the venv can't see them. The
installer creates the venv with `--system-site-packages` for this reason — check
it with:

```bash
~/.local/share/unweave/.venv/bin/python -c \
  "import gi; gi.require_version('WebKit2','4.1'); from gi.repository import WebKit2; print('ok')"
```

If that fails, install the packages and re-run the installer. If you set
`UNWEAVE_BROWSER=1`, browser mode is intentional.

**Playback clips for a moment, then goes silent in the native window (known issue).**
Seen on Ubuntu 24.04 (WebKitGTK 2.4x, PipeWire). The native window plays audio through
WebKitGTK's Web Audio, which decodes with GStreamer. Its FLAC decoder logs
`flacdec: Lost sync, flushing decoder` on the 24-bit FLAC stems, and even with the stems
converted to WAV the output was a ~0.3 s burst followed by silence. The audio device
itself is fine, and Chrome plays the same project correctly. Not fixed in-engine; use
browser mode (or the in-app **Open in browser** banner):

```bash
UNWEAVE_BROWSER=1 unweave
```

**"FFmpeg was not found."**
Run the app's first-run setup, or install FFmpeg from your distro
(`sudo apt install ffmpeg`) and reopen the app.

**Automatic FFmpeg setup fails on ARM.**
The static FFmpeg build the app downloads is x86-64 only. On arm64, install FFmpeg
with your package manager instead — the app finds it on `PATH`.

**`unweave: command not found`.**
`~/.local/bin` isn't on your `PATH`. Either add it, or launch with the full path
`~/.local/bin/unweave`.

## Notes for maintainers

- The Linux installer is the counterpart to `installer/bootstrap.ps1` (dependency
  setup) plus `installer/Unweave.nsis` (launcher, menu entry, uninstall). NSIS
  has no Linux equivalent here because there's no prebuilt Python runtime to ship;
  the script builds a venv instead.
- `app/unweave/setup_env.py` picks the FFmpeg archive per platform — the
  gyan.dev `.zip` on Windows, the johnvansickle static `.tar.xz` on Linux,
  evermeet.cx zips on macOS — and sets the executable bit after extracting.
- `installer/Unweave.nsis` reads the app from `app/` and the packaging metadata
  from the repo root's `pyproject.toml`; `install-linux.sh` mirrors that layout so
  both installers stay in sync with one source tree.
