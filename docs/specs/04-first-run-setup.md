# 04 — First-run setup

Status: Doing

What this covers: setup downloads, consent and gating, in-app progress, and the remaining installer-to-app experience work.

## Purpose and download stages

The installer stays small and setup downloads dependencies after install, avoiding a multi-gigabyte installer and downloads for features the user may not need. Setup stages and approximate sizes:

| # | Component | Approx. size | Trigger / behavior |
|---|---|---:|---|
| 1 | Embedded Python runtime, `uv`, and app packages such as pywebview | 40–60 MB | First launch when the runtime is absent. |
| 2 | FFmpeg and ffprobe | 80–120 MB | First launch when not already available. |
| 3 | Separation engine (`torch`, `audio-separator`, ONNX Runtime, librosa, and related packages) | 1.3–1.8 GB | Required before separation can run. |
| 4 | YouTube support (`yt-dlp`) | about 15 MB | Optional; installed only when enabled/needed. |
| 5 | AI model checkpoints (Demucs, MDX, RoFormer/guitar split) | about 80–500 MB each | Per-model lazy download on first use of a preset/feature. |

Stages 1–3 together are roughly 1.5–2.0 GB depending on platform/package versions; stage 4 is optional. Model downloads are separate and remain lazy per model. A model download is part of the user's explicit separation/split action and reports job progress.

## Current implementation

- [x] In-app `#view-setup` checklist lists setup components and availability.
- [x] Per-stage progress bars/status are shown during setup jobs.
- [x] Required stages gate separation and show a setup banner when work is blocked.
- [x] YouTube support has an optional toggle; required setup items cannot be opted out of.
- [x] “Not now” defers setup; unavailable actions remain gated and can return the user to setup.
- [x] `setup_env.py` jobs report setup progress through the job/state UI rather than relying solely on the bootstrap console.
- [x] Per-model downloads remain lazy and report progress during the associated job.

## Intended consent and first-run flow

Before a download of roughly 1.5 GB begins, the user should see what is required and explicitly approve it. The required runtime, FFmpeg, and separation-engine entries are informational/locked; YouTube support is a genuine optional choice. “Not now” keeps the app available but actions requiring missing components route back to setup. Do not show model downloads as a separate setup prerequisite: they stay attached to the separation or guitar-split action that needs them.

The checklist, consent and gating are in the running app, and the shipped NSIS installer reaches it without a console step (`bootstrap.ps1` is a legacy developer script, not part of the shipped flow). The design intent is to make setup feel like the app's primary first-run experience, with the normal chrome and content transition rather than a visually separate utility screen.

## Remaining work

- [x] Approval before the ~1.5 GB download: the shipped installer (`Unweave.nsis`) bundles the embedded Python runtime (stage 1), and stages 2–3 start only from the in-app setup checklist, which lists sizes, keeps YouTube optional and offers "Not now".
- [x] No raw console on the shipped path: `installer/bootstrap.ps1` is a legacy developer script that the NSIS installer does not run. Users reach the app UI first.
- [x] Stages 2–4 install inside the running app's setup job (`setup_env.run_setup`) with per-stage progress, cancel, and pip repair/retry.
- [ ] Complete the visual merge so setup feels like the main UI during first run, rather than a separate setup screen.
- [ ] End-to-end verify a fresh install in a real Program Files location, including consent, progress, completion, restart, and normal app use.
- [ ] Rebuild/package and publish a release after the real-install verification.

## Constraints

- Do not change `writable_dirs()` / `known_folder()`; the OneDrive-aware writable-directory behavior is a confirmed fix.
- Do not change `launch.bat` or the NSIS shortcut fixes.
- Do not change the `_install_dir()` fix (`parents[1]`, not `parents[2]`).
- Keep per-model downloads lazy; do not make every model a first-run prerequisite.

## Related

- [01 — App specification](01-app.md) — setup view, gating, and overall architecture.
- [Documentation status board](README.md) — authoritative feature status.
