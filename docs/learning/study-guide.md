# Unweave — Condensed technical study guide

Companion to `notebooklm-pack.md`. Upload this together with the core docs.

## One-sentence definition

Unweave is a **local** desktop stem separator: a Python package runs Demucs/MDX/RoFormer
on your machine, a stdlib HTTP server exposes a job API on loopback, and a vanilla-JS
UI (inside pywebview) drives import → separate → mix → export.

## Layers (remember this order)

```
Web UI (web/js)  --poll GET /api/state-->  HTTP server (webui/server.py)
                                              |
                                              v
                                         Job queue (webui/library.py)
                                              |  spawn + read stdout/stderr lines
                                              v
                                    Worker: python -m unweave
                                              |
                                              v
                         Engines: FFmpeg · PyTorch · ONNX Runtime
                                              |
                                              v
                              Project folder on disk (atomic publish)
```

Important asymmetry:

- **Worker → queue:** push/stream (CLI prints markers on stderr; queue parses lines).
- **UI → server:** poll (`app.js` every ~1 s while busy, ~2.5 s idle). Not WebSocket.

## Seven stages of one separation

1. **Entry** — UI `POST …/separate` → queue checks free space → staging folder → spawn worker.
2. **Plan** — `resolve_plan()` / `model_request()` / `select_model()` (no audio yet).
3. **Prepare** — `normalize()` via FFmpeg → 44.1 kHz stereo WAV inside staging.
4. **Stem pass** — Demucs or MDX (~1× realtime on CPU reference machine).
5. **Guitar split** (optional) — RoFormer lead/rhythm (~10× the stem pass).
6. **Assemble + publish** — fold into `other`, validate, write `separation.json`, rename staging → `stems/`.
7. **After** — UI fetches FLAC stems into Web Audio mixer; optional export job.

## Model selection (invariant)

| Request | Model | Backend |
|---|---|---|
| Only vocals + instrumental | `UVR_MDXNET_KARA_2` | ONNX Runtime (CPU) |
| Any other multi-stem plan | `htdemucs_6s` (always all 6) | PyTorch |
| Lead/rhythm after guitar | `lead_rhythm_listra92` | PyTorch RoFormer |
| Explicit `--model htdemucs` | 4-stem Demucs | never auto-selected |

`htdemucs_6s` always computes six stems; `_collect()` drops what the plan does not keep
or fold. Switching models “to save work” would change `other` and break identical plans.

## Design rules that prevent real bugs

1. **One model for every multi-stem plan** — `other` must mean the same residual.
2. **Compute once, then drop** — extra inference beats inconsistent audio.
3. **Publish atomically** — staging → backup swap → restore on failure; never half a set.
4. **Scratch inside job staging** — even `input.wav`; leftover scanner can find it.
5. **Child processes die with the job/app** — Windows Job Object / process group via `processes.popen()`.
6. **Check free space before write** — separate / export / import.
7. **Two progress numbers** — `progress` (whole job) vs `step_progress` (current step).
8. **Every job leaves a log file** — UI log is trimmed; disk log is the diagnosis trail.
9. **Leave a core free** — `cpu_threads()`; CPU builds usually one concurrent job.
10. **UI process never imports torch** — CUDA probe reads installed files only.

## Package map

| Area | Responsibility |
|---|---|
| `audio/pipeline.py` | Full separate path |
| `audio/guitar_split.py` | Lead/rhythm |
| `audio/model_cache.py` | Download + SHA-256 + separator factory |
| `audio/exports.py` | Re-encode + optional limiter |
| `webui/server.py` | Loopback HTTP + static `web/` + session token |
| `webui/library.py` | Queue, spawn, progress parse, imports/exports |
| `projects/store.py` | On-disk project format |
| `setup_env.py` | First-run FFmpeg / separation / YouTube stages |
| `processes.py` | Killable process trees |
| `web/js/*` | Vanilla ES modules, no build step |

## Desktop packaging ideas

- Tiny installer (NSIS) + embedded Python; **heavy ML deps downloaded on consent**.
- Window = pywebview (OS WebView), not Electron Chromium.
- Rejected: Tauri (Rust rewrite), Electron (size), monolithic PyInstaller (~500 MB).

## Spec board (mental model)

Read specs in order 01 → 13 when deepening. Status lives in `docs/specs/README.md`.
Backlog highlight: GPU acceleration (spec 11). Most job/UX specs are Done.

## Privacy / trust boundary

- Audio stays on disk; no cloud separation.
- Network only for: model downloads, YouTube import, MusicBrainz/cover lookup, update check.
- Server binds `127.0.0.1:8765` with a per-session token.

## Timing intuition (CPU, i5-12400 reference)

| Stage | Rough cost |
|---|---|
| Stem pass `_run_demucs()` | ~0.22 s per second of audio (~1×) |
| Guitar `split_guitar()` | ~2.4 s per second of audio (~10×) |
| Mix `other.flac` | under a second |

That is why dual-pass jobs need separate step progress — a single bar would freeze during the split.
