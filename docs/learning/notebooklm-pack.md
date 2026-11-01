# Unweave — NotebookLM all-in-one

**Zero-effort path:** upload *only this file* into [NotebookLM](https://notebooklm.google.com/)
(or paste its raw GitHub URL after it is on `main`). Then send: `Start tutoring`.

Raw URL (after push):

```
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/learning/notebooklm-pack.md
```

This document is self-contained. Extra repo docs are optional later, not required.

---

## Tutor instructions (for NotebookLM)

When the learner says **Start tutoring** or asks anything about Unweave, follow these rules:

1. Ground answers in **this source**. Prefer architecture and design rules over trivia.
2. Always name layers when explaining a flow:
   `UI → HTTP server → job queue → worker (python -m unweave) → engines → disk`.
3. Call out invariants: atomic publish, one multi-stem model, scratch inside staging,
   process-tree kill, stderr stream vs UI poll.
4. Keep answers short: overview → bullets → one check question.
5. If asked to quiz, ask one question at a time and wait.
6. Suggested first reply after “Start tutoring”:
   - 8-bullet “Unweave in one screen”
   - text layer diagram
   - ask which track they want: Pipeline / Jobs+progress / Packaging / Design-rules quiz

---

## What Unweave is

Local desktop stem separator. A song becomes vocals, drums, bass, guitar, piano, other
(optional guitar lead/rhythm). No account, no cloud separation, no telemetry.

- Python package: `unweave` under `app/unweave/`
- UI: vanilla JS in `web/`, no build step, shown in pywebview
- Server: stdlib `http.server` on `127.0.0.1:8765` with a per-session token
- Based on Sound Razor; cache folder stays `.sound-razor/` for compatibility

Network only for: model downloads, YouTube import, MusicBrainz/covers, update check.

---

## Layer diagram

```
Web UI (web/js)
   |  poll GET /api/state  (~1 s busy, ~2.5 s idle)
   v
HTTP server (webui/server.py + router/routes)
   |
   v
Job queue (webui/queue.py via Library)
   |  spawn subprocess + read stdout/stderr line by line
   v
Worker: python -m unweave
   |
   v
Engines: FFmpeg · PyTorch · ONNX Runtime
   |
   v
Project folder on disk (atomic publish into stems/)
```

Asymmetry (important):

- **Worker → queue:** stream/push (CLI markers on stderr).
- **UI → server:** poll. Not WebSocket. Fine for a local 1-user app with minute-scale jobs.

---

## Seven stages of one separation

1. **Entry** — `POST /api/projects/{id}/separate` → free-space check → `.separation-*`
   staging → spawn `python -m unweave separate`.
2. **Plan** — `resolve_plan()` / `model_request()` / `select_model()` (no audio yet).
3. **Prepare** — `normalize()` via FFmpeg → 44.1 kHz stereo WAV inside staging.
4. **Stem pass** — Demucs or MDX (~1× realtime on CPU reference).
5. **Guitar split** (optional) — Mel-Band RoFormer lead/rhythm (~10× stem pass).
6. **Assemble + publish** — fold into `other`, `validate_outputs()`, `separation.json`,
   swap staging → `stems/` (restore backup on failure).
7. **After** — UI loads FLAC into Web Audio mixer; optional export job.

CLI enters at the same worker as the queue (`python -m unweave …`).

---

## Models and backends

| When | Model | Backend | Where in code |
|---|---|---|---|
| Only vocals + instrumental | `UVR_MDXNET_KARA_2.onnx` | ONNX Runtime (CPU) | `pipeline.py` + `model_cache.create_separator()` via audio-separator |
| Any other multi-stem plan | `htdemucs_6s` (always emits 6) | PyTorch (Demucs) | same path |
| Guitar lead/rhythm | `lead_rhythm_listra92.ckpt` | PyTorch (RoFormer) | `guitar_split.py` + `vendor/roformer/` |
| Explicit `--model` only | `htdemucs` (4-stem) | PyTorch | never auto-selected |

Weights: SHA-256 pinned via `model_cache.cached_download()`.

`htdemucs_6s` always computes all six; `_collect()` drops unneeded stems. Do not switch
to a 4-stem model “to save work” — that changes what `other` means.

---

## Timing (CPU, i5-12400, ~355 s track)

| Stage | Function | Cost |
|---|---|---|
| Stem pass | `_run_demucs()` | ~0.22 s / s of audio (~1×) |
| Guitar split | `split_guitar()` | ~2.4 s / s of audio (~10×) |
| Mix `other.flac` | `mix_stems()` | under a second |

Dual-pass jobs need **step** progress; one shared bar would freeze during guitar.

---

## Jobs, progress, logs

- Queue runs jobs (one per project; CPU builds usually max 1 concurrent).
- Progress markers come from CLI stderr; `progress.track_progress()` updates the job dict.
- UI reads snapshot via `GET /api/state` (`web/js/app.js` poll loop).

| Field | Meaning |
|---|---|
| `progress` | Whole-job 0–100 (nav / queue / badge) |
| `step_progress` | Current step 0–100 (detail ring) |
| `eta` / `step_eta` | Whole-job vs step remaining |
| `pass_index` / `pass_count` | Dual-pass caption (e.g. Step 1 of 2) |

Steps: `prepare` → `load` → `separate` → `guitar` → `finalize`.

Every job writes a disk log under the config logs dir; the in-memory UI log is trimmed.

---

## Design rules (memorize these)

1. **One model for every multi-stem plan** — `other` must stay the same residual.
2. **Compute once, then drop** — consistency > skipping inference.
3. **Publish atomically** — staging + backup swap; never half a stem set.
4. **Scratch inside job staging** — even `input.wav` (not `%TEMP%`).
5. **Child processes die with job/app** — `processes.popen()` Job Object / process group.
6. **Check free space before writing.**
7. **Two progress numbers** — whole job vs step.
8. **Every job leaves a log file.**
9. **Leave a core free** — `cpu_threads()`; UI stays responsive.
10. **UI process never imports torch** — `setup_env.torch_has_cuda()` inspects files only.

---

## Module cheat sheet

| Concern | File |
|---|---|
| Separation orchestration | `app/unweave/audio/pipeline.py` |
| Guitar lead/rhythm | `app/unweave/audio/guitar_split.py` |
| Model download / SHA / separator | `app/unweave/audio/model_cache.py` |
| Export | `app/unweave/audio/exports.py` |
| HTTP API | `app/unweave/webui/server.py` + `router.py` / `routes/` |
| Job queue | `app/unweave/webui/queue.py` (`JobQueueMixin`) |
| Progress parse | `app/unweave/webui/progress.py` |
| Library façade | `app/unweave/webui/library.py` |
| Project on disk | `app/unweave/projects/store.py` |
| First-run install | `app/unweave/setup_env.py` |
| Process tree kill | `app/unweave/processes.py` |
| UI poll | `app/unweave/web/js/app.js` |
| Progress UI | `app/unweave/web/js/features/progress.js` |

Frontend folders: `js/core/`, `js/chrome/`, `js/views/`, `js/features/`, `js/audio/`.
CSS: six stylesheets under `web/css/`.

---

## Tech stack & packaging

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11 | Audio/ML ecosystem |
| HTTP | stdlib `http.server` | Tiny, loopback + token |
| UI | Vanilla JS/CSS | No build step |
| Inference | audio-separator + torch + onnxruntime | Demucs/MDX/RoFormer |
| Window | pywebview | OS WebView, no Chromium bundle |
| Installer | NSIS + embedded Python | Tiny setup; heavy deps on consent |
| Linux | bash + `uv` venv | No portable embeddable runtime |

Rejected: Electron (size), Tauri (Rust rewrite), monolithic PyInstaller (~500 MB),
bundling PyTorch in the installer (~2 GB for everyone).

First-run stages (approx): FFmpeg → separation engine (PyTorch etc.) → YouTube (yt-dlp).

---

## Privacy / trust

- Audio never uploaded for separation.
- Loopback-only server + session token.
- Canonical stems: FLAC.

---

## Built-in lesson prompts (paste into chat)

**Start**

```
Start tutoring
```

**Pipeline deep dive**

```
Walk the 7 separation stages. For each: key functions, disk outputs, failure mode.
Focus on select_model() and atomic publish.
```

**Jobs & progress**

```
Explain stderr streaming vs UI polling, and progress vs step_progress.
Argue why polling beats WebSocket for this local app.
```

**Packaging**

```
Why NSIS + embedded Python + pywebview + first-run download, not Electron/Tauri?
```

**Quiz mode**

```
Quiz me on the 10 design rules. One question at a time. Wait for my answer.
```

**Success check** (answer without notes)

1. Why the UI never imports torch.
2. Why multi-stem plans always use `htdemucs_6s`.
3. How cancel avoids half-written stems.
4. How progress reaches the UI (stderr → queue → poll).
5. What runs in-process vs in the worker subprocess.

---

## Optional later sources (not required)

Only if you want more depth after this file:

```
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/architecture.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/05-job-queue.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/09-job-progress.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/01-app.md
```
