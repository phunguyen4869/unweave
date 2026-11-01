# Technical Stack

## Core (`app/unweave/`)

| Layer | Technology | Why |
|---|---|---|
| Language | Python 3.11 | Audio/ML ecosystem, and the upstream core is already Python |
| CLI | argparse | stdlib, no extra deps |
| HTTP server | `http.server` (stdlib) | No framework needed, tiny attack surface, loopback + token |
| Frontend | Vanilla JS, HTML, CSS | No build step, no framework overhead, six stylesheets |
| Audio playback | Web Audio API + AudioBufferSourceNode | Native browser audio, sample-accurate stem sync |
| Tempo/pitch | SoundTouchJS (MPL-2.0) | Pitch-preserving speed change in an AudioWorklet |
| Inference | audio-separator (wraps Demucs + MDX) | Pretrained models, handles model download/caching |
| Deep learning | PyTorch (Demucs, RoFormer) + ONNX Runtime (MDX) | Industry standard, good CPU performance |
| Youtube | yt-dlp | Handles JS challenges and format negotiation |
| Metadata | MusicBrainz API + Cover Art Archive | Free, open music database, rate-limited to 1 req/s |
| Audio I/O | FFmpeg, soundfile, numpy, librosa | Normalisation, mixing, export encoding, analysis |

## Desktop packaging (`um1chc5/unweave`)

| Layer | Technology | Why |
|---|---|---|
| Installer | NSIS (`installer/Unweave.nsis`) | Free, scriptable, produces a real Windows installer; no network at install time |
| Launcher | NSIS (`installer/launcher.nsi`) | Builds `Unweave.exe`, console-less, waits on the app |
| Embedded runtime | Python 3.11.9 embeddable + pip + pywebview | Tiny install; no system Python needed |
| Native window | pywebview | Reuses the existing web UI in the OS WebView, no Chromium bundle |
| Linux install | bash + `uv` | No portable embedded interpreter, so a venv is built per machine |
| Heavy deps | first-run setup screen | ~1.7 GB fetched on consent instead of shipped |

## Alternatives considered

| Option | Rejected because |
|---|---|
| Inno Setup | Was planned, but NSIS gives a smaller installer and builds the launcher in the same pass |
| Tauri | Requires a Rust rewrite of the backend — too big a lift for an existing Python codebase |
| Electron | ~150 MB Chromium bundle defeats the size-reduction goal |
| PyInstaller monolithic bundle | ~500 MB installer is too large for non-IT users |
| WPF/WinForms wrapper | Requires rewriting the UI in C# — abandons the working web UI |
| py2exe | Abandoned, poor Python 3.11 support |
| Bundling PyTorch in the installer | ~2 GB download for every user, including those who skip optional stages |
