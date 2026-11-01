# Unweave specifications

Unweave is a local desktop stem separator with a Python backend and vanilla ES-module web UI; it requires no account and collects no telemetry. The specifications below describe the current app and planned work while keeping canonical audio and user projects local.

## Ordered specification and status board

| # | Spec | Status | Summary / what remains |
|---:|---|---|---|
| 01 | [App specification](01-app.md) | Done | Describes current behavior and architecture, implemented project fields, and the current layout after the module refactor. |
| 02 | [Pre-separation trim](02-pre-separation-trim.md) | Done | Overall and guitar-section trim, project-timeline offsets, offset-aware playback, trim editors, and CLI/API support are implemented. |
| 03 | [Output formats](03-output-formats.md) | Done | Export job, six-format FFmpeg matrix, staging, manifest, reveal route, dialog, and progress are implemented. Canonical stored stems are FLAC (lossless, ~40–50% smaller than WAV). |
| 04 | [First-run setup](04-first-run-setup.md) | Doing | Installer ships the runtime; consent, checklist, per-stage progress and gating run in-app (no console step). Remaining: visual merge of setup into the main UI, fresh Program Files install test, release. |
| 05 | [Job queue and concurrency](05-job-queue.md) | Done | Jobs queue and run one at a time on CPU (derived cap: 3 on a CUDA build, RAM-capped, env override). Decided: no concurrency setting, no queue depth cap. |
| 06 | [Close behavior](06-close-behavior.md) | Done | Confirm-on-close, clean cancel of the whole process tree (Windows Job Object kill-on-close), stale-staging sweep. Queued jobs are cancelled on close. Job-state persistence deferred. |
| 07 | [Disk usage and cache](07-disk-usage.md) | Done (Phase 2) | FLAC stems, staging sweep, Windows uninstall model prompt, disk-space precheck before separation/export/import. Stem sizes documented in the README. Remaining: Linux `--purge`, size/cleanup UI. |
| 08 | [Performance and hidden optimizations](08-performance.md) | Done (Items 1–2) | CPU-derived threads, no redundant stem copy, no torch import in the UI process. Parallel jobs share the cores. Remaining: real guitar-split thread benchmark; GPU path is backlog spec 11. |
| 09 | [Job progress and ETA](09-job-progress.md) | Done | Overall `%` is elapsed+ETA weighted (≈10× prior only before guitar runs); detail panel is step-first (`step_eta`, pass caption, “Whole job” line); soft advanced-plan warning when lead/rhythm split is on. |
| 10 | [In-app update check](10-updates.md) | Done | First-launch consent (Allow / Not now + don’t ask again); throttled GitHub Releases check; banner + open download; no auto-install. |
| 11 | [GPU acceleration](11-gpu-acceleration.md) | Backlog | Opt-in CUDA build of PyTorch for NVIDIA users; guitar split and Demucs on the GPU with CPU fallback and a VRAM-aware job cap. Needs an NVIDIA machine to build and test. |
| 12 | [Settings panel](12-settings-panel.md) | Backlog | One place for components, storage cleanup, projects folder, update checks and language. Deferred until at least two sections have real content. |
| — | Web module/CSS refactor | Done | ES modules are under `web/js/`; six CSS files are under `web/css/`; static serving uses generic safe handling. |
| — | Python package refactor | Done | Split into `audio/`, `projects/`, and `webui/` is complete; package-layout smoke tests pass. |

### How to read status

The status board is the single source of truth: **Done** means the described behavior/refactor is complete, **Doing** means work is underway with remaining items called out, **Todo** means specified but not implemented, and **Backlog** means written down and deliberately not scheduled yet. Individual feature specs include implementation checklists; those checklists do not override this board.

## Read in order

1. [01 — App specification](01-app.md)
2. [02 — Pre-separation trim](02-pre-separation-trim.md)
3. [03 — Output formats](03-output-formats.md)
4. [04 — First-run setup](04-first-run-setup.md)
5. [05 — Job queue and concurrency](05-job-queue.md)
6. [06 — Close behavior](06-close-behavior.md)
7. [07 — Disk usage and cache](07-disk-usage.md)
8. [08 — Performance and hidden optimizations](08-performance.md)
9. [09 — Job progress and ETA](09-job-progress.md)
10. [10 — In-app update check](10-updates.md)
11. [11 — GPU acceleration](11-gpu-acceleration.md) (backlog)
12. [12 — Settings panel](12-settings-panel.md) (backlog)

See the [docs index](../README.md) for architecture, project overview, and desktop packaging documentation.
