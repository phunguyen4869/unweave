# 01 — Unweave application specification

Status: Done

What this covers: the current product, its behavior and architecture, plus the project fields and package layout.

## Product

Unweave is a local desktop stem separator. A Python backend exposes a local HTTP API and a vanilla ES-module web UI runs in a pywebview desktop window. Users import audio, separate it into stems, organize projects, and play or mix the results. The app requires no account and sends no telemetry; audio and projects stay on the user's machine. Optional metadata lookup contacts MusicBrainz/Cover Art Archive, and optional YouTube import downloads the selected audio source.

### Goals

- Make local audio separation, project management, and stem playback accessible from a desktop app.
- Keep canonical project audio lossless and usable for repeat processing.
- Run inference locally with lazy model downloads and show progress for long-running work.
- Keep the browser-based UI independent of a frontend framework.

### Non-goals

- Cloud processing, accounts, analytics, or telemetry.
- Audio mastering, training models, or editing the original recording destructively.
- Batch production workflows or a general-purpose DAW.

## Architecture

| Layer | Responsibility |
|---|---|
| CLI and pipeline | Command entry points and separation orchestration: normalize input with FFmpeg, select/load a model, run inference, and write validated stems. |
| Project library | Create, inspect, update, and delete project folders; track jobs and metadata; validate filesystem operations. |
| Local HTTP UI | Serve the web app and project/job APIs on loopback, with a per-session token and static-file safety checks. |
| Desktop launcher | Start the local service and display it in a native pywebview window with app chrome. |
| Static web app | Vanilla ES modules for New, Library, Song, and Setup views, plus CSS assets. |

The Python package split into `audio/`, `projects/`, and `webui/` is complete. The responsibilities and paths below describe the current layout; see [architecture](../architecture.md) for the technical data flow.

## Project data model

A project is a directory containing the original source, generated stems, and JSON metadata. The original is retained unchanged.

```text
<project>/
├── original.<source extension>     # imported audio, retained in full
├── metadata.json                   # user/editable tags and lookup results
├── stems/
│   ├── separation.json             # model, selected stems, settings, warnings
│   ├── vocals.wav                  # canonical working stems (44.1 kHz stereo)
│   ├── guitar.wav
│   └── ...
└── exports/                        # on-demand copies; not canonical
    └── manifest.json
```

`describe_project()` presents original-file details, metadata, available stems, byte/version information, and warnings. Each stem carries a project-timeline `offset`; the default is zero. Optional `separation.json` trim settings record the absolute project-time section for main stems and guitar-split stems. Export copies and their manifest live in `exports/`; stored stems remain canonical 44.1 kHz stereo WAV. See [02 — Pre-separation trim](02-pre-separation-trim.md) and [03 — Output formats](03-output-formats.md).

## Separation pipeline

1. Import a local audio file or (when enabled) download audio from YouTube. Preserve the original in the project.
2. FFmpeg normalizes model input to stereo 44.1 kHz WAV.
3. Select a separation model based on the requested preset/stems. Demucs, MDX/ONNX, and RoFormer model files are cached and downloaded lazily when first required.
4. Run local inference and validate outputs. Selected stems are written; unselected parts are folded into `other` where applicable.
5. Optionally run the guitar lead/rhythm splitter on `guitar.wav`. The source guitar stem remains available.

FFmpeg is used for normalization, section trimming, export conversion, and media operations. The model cache tracks download/checksum state. See specs 02 and 03 for trimming and export behavior.

## Web UI

| View/component | Behavior |
|---|---|
| New | Import a local file or optional YouTube source, choose a separation preset/stems, and start a job. |
| Library | Browse, search, and manage local projects. |
| Song | View/edit metadata, inspect stems, open the project folder, delete, and play/mix stems. |
| Setup | Show required and optional setup components and their stage progress; gate actions until required setup is complete. See [04 — First-run setup](04-first-run-setup.md). |
| Player | Web Audio playback of original and stems, with SoundTouch worklet support for tempo/pitch-preserving speed changes. Trimmed projects play as a section from 0 to the section length. |
| Transport and mixer | Seek/play/pause, track mute/solo, volume, and synchronized stem playback. |
| Progress | Job status, stage progress, logs, and cancellation where supported. Overall `%` is time-weighted for dual-pass jobs; the detail panel is step-first (ring / step time left) with a labelled whole-job line; see [09 — Job progress and ETA](09-job-progress.md). |
| Metadata lookup | Optional MusicBrainz and Cover Art Archive lookup; results can populate project metadata. |
| Folder picker | Desktop bridge supports choosing a local project-library folder. |
| Window chrome | Desktop title bar and app controls are provided by the desktop shell, not browser chrome. |
| About / updates | Version and credits; optional GitHub Releases check after consent. See [10 — In-app update check](10-updates.md). |

## First-run setup

The in-app setup view lists runtime, FFmpeg, separation engine, optional YouTube support, and lazy per-model downloads. Required stages gate separation; YouTube support is optional. The in-app checklist, per-stage progress, optional toggle, setup gating, banner, and `setup_env.py` job progress exist. The installer consent/bootstrap experience and full visual integration of setup as the primary UI remain. See [04 — First-run setup](04-first-run-setup.md) for the status and remaining work.

## Code layout

```text
audio/
  pipeline.py       # normalization, model selection and separation
  guitar_split.py   # lead/rhythm inference
  model_cache.py    # model downloads, cache and checksums
  sources.py        # optional source downloads
projects/
  store.py          # project discovery and data model
  metadata.py       # tags and metadata lookup
webui/
  server.py         # local HTTP server, routes, static assets
  library.py        # project operations and background jobs
setup_env.py        # setup-stage detection and installation jobs
web/
  js/               # vanilla ES modules and views
  css/              # component/view stylesheets
```

The Python package migration to this layout is complete. Web JavaScript and CSS have been refactored to ES modules under `web/js/` and six stylesheets under `web/css/`.

## Security and operations

- Bind the service to `127.0.0.1` only; do not expose it to the LAN.
- Require the generated session token on API requests originating from the UI.
- Apply a restrictive Content Security Policy and serve only known static assets through generic safe-path handling.
- Validate project-relative paths and reject traversal, symlink escapes, and arbitrary filesystem targets.
- Local audio is not uploaded to a cloud service. Optional third-party metadata/source requests are user-initiated and are distinct from telemetry (none is collected).
- Long-running separation/setup work runs as jobs with progress and cancellation where supported; models are cached locally.
