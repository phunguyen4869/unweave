# 13 — Leftover clean-up and the startup dialog

Status: Done

What this covers: finding and removing files Unweave itself left behind (temp folders,
staging folders from interrupted jobs, unfinished downloads), how the user is asked,
the combined startup dialog it shares with the update question, the installer's
"Run Unweave now" finish page, and the two root-cause fixes that stop most leftovers
being created.

## Why

Found on a real machine (Nov 1):

| Where | What | Size |
|---|---|---:|
| `%TEMP%\sound-razor-ffmpeg-*` | 8 × `ffmpeg.zip`, 0.9–16.8 GB each, all from one morning of development | 52.7 GB |
| `%TEMP%\sound-razor-*` | `input.wav` from separations that were interrupted (one 1.4 GB) | 1.6 GB |
| `%TEMP%\unweave-*` | the same, from 1.4.x | 63 MB |

The 52.7 GB was a broken development test (a fake download that never ended), not a
user download. But nothing in the app ever removes any of it, and two real gaps remain
in 1.4.x:

1. **Interrupted jobs always leave their temp folder.** `pipeline.separate()` converts
   the song into `%TEMP%\unweave-*\input.wav`. `TemporaryDirectory` only cleans up if
   the process exits normally; cancel and close end the process tree (spec 06), so
   the cleanup never runs.
2. **The existing startup sweep misses most staging folders.**
   `Library.sweep_stale_staging()` only looks at the **top level of the projects
   folder**, but `.separation-*`, `.exports-*` and `.cover-*` are created **inside each
   project**, and `.model-download-*` inside the **model cache**. None of those is
   ever swept today (spec 06 says they are; it is wrong).
3. **The FFmpeg download has no size cap.** `setup_env._install_ffmpeg()` writes until
   the server stops sending. A misbehaving server or proxy could fill the disk exactly
   the way the broken test did.

## Root-cause fixes (do these first)

- **Cap the FFmpeg download.** Abort with "FFmpeg download was larger than expected"
  once `received` exceeds `Content-Length` (when given) or 500 MB (when not). Same
  treatment for `model_cache.cached_download()`, capped at `Content-Length` or 2 GB.
- **Keep job scratch out of `%TEMP%`.** Create the normalized `input.wav` inside the
  job's existing project-local staging folder (`.separation-*` / `.unweave-input-*`
  under the CLI `--output`), so an interrupted job's leftovers live where the sweep
  can find them, on the drive the disk-space precheck already checked. The import
  upload buffer (`unweave-upload-*`) stays in `%TEMP%` (the projects root is not known
  when the upload begins) and is covered by the clean-up below.

## What counts as a leftover

A single scanner, `unweave/cleanup.py`, returns candidates. **Only** these, and only
when every rule below also holds:

| Group | Location (scanned depth) | Name patterns | Kind |
|---|---|---|---|
| Temp files | `tempfile.gettempdir()` or `UNWEAVE_CLEANUP_TEMP` (top level only) | `unweave-*`, `unweave-ffmpeg-*`, `unweave-upload-*`, `sound-razor-*`, `sound-razor-ffmpeg-*` | folders |
| Interrupted jobs | projects root (top level) | `.separation-*`, `.youtube-*`, `.import-*`, `.exports-*`, `.guitar-split-*`, `.stems-*` | folders |
| Interrupted jobs | each project folder (top level) | `.separation-*`, `.exports-*`, `.guitar-split-*`, `.stems-*` | folders |
| Interrupted jobs | each project folder (top level) | `.cover-*` | files |
| Unfinished downloads | model cache folder (top level) | `.model-download-*` | folders |

**App-data note:** under `%LOCALAPPDATA%\Unweave`, setup creates permanent `packages/`,
`ffmpeg/`, `models/` and `ui.json`. FFmpeg archives download into system temp as
`unweave-ffmpeg-*`. pip `--prefix` installs directly into `packages/` and does **not**
leave `.packages-*` or `pip-*` folders there, so those patterns were omitted.

Rules, all of which must hold for each item:

- **Older than 24 hours** (`mtime` of the entry itself). Anything younger may belong
  to a job that is still running, in this or another Unweave window.
- **No job is running or queued** in this app when scanning *and* when deleting.
- **Never follow links**: skip any symlink or junction (mount-point / symlink reparse
  tags only — OneDrive cloud placeholders are sized normally), and never descend into
  one when sizing.
- **Re-check right before deleting**: same path, still matches a pattern, still old
  enough, still not a link. The scan result is only a proposal.
- **Never** touch, at any depth: a project's original audio, `stems/`, `exports/`,
  `metadata.json`, `cover-*` images, `separation.json`; the model files themselves;
  setup's `packages/` and `ffmpeg/`; `ui.json`; `logs/` (already pruned to the newest
  N by `prune_job_logs`). Clearing models stays the separate, explicit button in
  Settings (spec 12).
- Nothing outside the roots in the table. No pattern is ever matched below the
  listed depth.

Sizing walks only matched entries, so the scan is cheap: a directory listing of
`%TEMP%`, the projects root, each project folder and the model cache. Target:
under one second on a library of a few hundred songs; if the walk is slower than 3 s,
stop sizing and report "more than X" rather than blocking. Snapshot under
`Library.lock`, size without it (same pattern as `storage_info`).

## When and how the user is asked

### Background scan

On every launch, after the window is up and first-run setup is complete or declined,
`/api/startup` runs the scan (once) and applies the silent rule. Expose the result in
`/api/state` as `cleanup: {bytes, count, scanned_at, prefs, notice}`.

| Found | Behaviour |
|---|---|
| Nothing | Nothing. |
| Under 50 MB total | Remove silently (same safety rules); no dialog. Like today's staging sweep, this is always junk and not worth a question. |
| 50 MB or more, auto-clean **off** | Offer it in the startup dialog (below). |
| 50 MB or more, auto-clean **on** | Remove silently, then a notice: "Freed 1.6 GB of leftover files." |

The preference lives in `ui.json` next to the update settings:
`cleanup: {auto: false, dont_ask: false}`.

### The startup dialog (shared with the update question)

One startup dialog shows only the sections that apply on this launch, in this order.
If no section applies, it does not open. It never opens on top of first-run setup.

1. **Check for updates** — exactly today's consent (spec 10): Allow / Not now, with
   its own "Don't ask again".
2. **Clean up leftovers** — grouped list with sizes and counts (expandable to paths).
   Buttons: **Clean up** and **Not now**; checkboxes "Clean up automatically from now
   on" and "Don't ask again". Cleaning shows progress, then "Freed X".

### Settings → Storage

"Leftover files" row: last scan ("1.6 GB in 14 items" or "Nothing to clean"),
**Scan again**, **Clean up** (same list + confirmation), and the auto switch.

## Installer finish page

NSIS Modern UI finish page with **Run Unweave now** (checked by default), launching
through Explorer so the app starts unelevated. Silent `/S` installs skip the page.

## API

- `GET /api/cleanup` — `{items, bytes, scanned_at, prefs, …}`
- `POST /api/cleanup/scan` — re-scan now.
- `POST /api/cleanup/run` — `{ids}` (default all). Re-validates; refuses while a job runs.
- `POST /api/cleanup/prefs` — `{auto, dont_ask}`.
- `GET /api/startup` — which dialog sections apply (runs the first scan if needed).

## Related

- [06 — Close behavior](06-close-behavior.md), [07 — Disk usage](07-disk-usage.md),
  [10 — Updates](10-updates.md), [12 — Settings panel](12-settings-panel.md).
