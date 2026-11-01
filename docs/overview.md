# Unweave — Project Overview

## What it is

Unweave is a local audio stem separator. It takes a song recording and splits it into
separate tracks — vocals, drums, bass, guitar, piano and the residual "other" — plus an
optional lead/rhythm split of the guitar. Everything runs on the machine it is installed
on: no account, no API key, no uploads.

It is based on [Sound Razor](https://github.com/pedromtcosta/sound-razor) by pedromtcosta,
which supplies the separation core. Unweave adds a rewritten UI, an advanced separation
plan, export, a job queue, and a native desktop install.

The Python package is `unweave` (`app/unweave/`). The on-disk model/cache folder stays
`.sound-razor/` so existing installs keep their downloaded weights without a migration.

## Two layers

### 1. Python application (`app/unweave/`)
- **CLI** — `python -m unweave` with `separate`, `split-guitar` and `ui` commands.
- **Separation pipeline** — `audio/pipeline.py`. FFmpeg normalises the input, a
  pretrained model runs inference, stems are assembled and published atomically.
- **Guitar split** — `audio/guitar_split.py`, using a vendored Mel-Band RoFormer to split
  the guitar stem into lead and rhythm.
- **Export** — `audio/exports.py` re-encodes copies into six formats with optional peak
  limiting.
- **Web UI server** — `webui/server.py` + Express-style `router.py` / `routes/` serve the
  local HTTP API and the static `web/` frontend (vanilla ES modules, no framework, no
  build step).
- **Job queue** — `webui/queue.py` (`JobQueueMixin` on `Library`) supervises separation
  subprocesses, one at a time per project, and streams progress (parsed in
  `webui/progress.py`) to the UI.
- **Metadata lookup** — `projects/metadata.py` queries MusicBrainz and Cover Art Archive.
- **YouTube import** — `audio/sources.py` wraps yt-dlp.

### 2. Desktop application
- `installer/Unweave.nsis` builds the Windows installer with NSIS; it ships a prebuilt
  embedded Python 3.11 runtime, so the user never touches Python, venv or PATH.
- `installer/launcher.nsi` builds `Unweave.exe`, the console-less launcher, which starts
  the local UI in a pywebview window.
- `installer/install-linux.sh` is the Linux counterpart: it builds a venv with `uv`,
  installs the app, and writes a launcher plus a `.desktop` entry.
- Neither installer downloads the heavy dependencies. PyTorch/audio-separator (~1.6 GB),
  FFmpeg and the model weights (~425 MB) are fetched by the app's own first-run setup
  screen, behind an explicit "Download & install" click.

## Project structure

```
unweave/
├── app/
│   ├── unweave/          # Python application package
│   │   ├── audio/            # pipeline.py, guitar_split.py, model_cache.py,
│   │   │                     # exports.py, output_files.py, sources.py
│   │   ├── projects/         # store.py (project format), metadata.py (MusicBrainz)
│   │   ├── webui/            # server + router/routes; library façade;
│   │   │                     # queue/settings/progress/plans mixins
│   │   ├── setup_env.py      # first-run dependency detection and install
│   │   └── web/              # static frontend: js/ ES modules, css/ six stylesheets
│   └── ui_entrypoint.py      # pywebview launcher
├── installer/                # Unweave.nsis, launcher.nsi, bootstrap.ps1,
│                             # install-linux.sh, embedded/ runtime
├── tests/                    # unit tests
├── docs/                     # this folder
├── pyproject.toml            # package config + extras
└── README.md                 # user-facing docs
```

## How separation works (simplified)

1. The user imports an audio file, or a YouTube link.
2. FFmpeg converts it to 44.1 kHz stereo PCM, applying any chosen trim.
3. One model is selected:
   - **htdemucs_6s** (vocals, drums, bass, guitar, piano, other) — the default for every
     multi-stem plan, and the only multi-stem choice.
   - **UVR_MDXNET_KARA_2** (vocals + instrumental) — only when the request is nothing but
     the karaoke pair, because no Demucs model can emit `instrumental`.
4. Inference runs on PyTorch, or ONNX Runtime for the MDX model.
5. Stems the plan keeps are written; stems the plan folds are mixed into `other.flac`;
   the rest are discarded. The model always computes all six.
6. Optionally, the guitar stem is split into lead and rhythm by the RoFormer model.
7. The result is published atomically — a cancelled or failed run never leaves half a
   stem set in the project folder.

## Key facts

- Model weights download on first use (~425 MB total) and are cached in
  `.sound-razor/models/`, verified against a pinned SHA-256.
- Inference only — nothing is trained locally.
- The server binds to loopback only (127.0.0.1:8765) and requires a per-session token.
- Canonical stems are FLAC; export can produce FLAC, MP3, Opus, M4A, WAV or AIFF.
- No cloud, no API keys, no telemetry.
