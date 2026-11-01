# 07 — Disk usage, cache, and uninstall

Status: Done (Phase 2 — FLAC stems, staging sweep, uninstall prompt, disk precheck, Linux `--purge`, size/cleanup UI in settings)

What this covers: everywhere the app writes to disk, what the realistic footprint is,
where the genuine disk-abuse risks are, and what the uninstallers do and do not
remove.

## Where everything lives

| Data | Windows | Linux | Removed on uninstall? |
|---|---|---|---|
| App code + embedded runtime | `%ProgramFiles64%\Unweave` | `~/.local/share/unweave` | **Yes** |
| Model cache | `%LOCALAPPDATA%\Unweave\models` | `~/.cache/unweave/models` | **No** |
| Config (`ui.json`) | `%LOCALAPPDATA%\Unweave\ui.json` | `~/.local/share/unweave/ui.json` | **No** |
| Projects (originals + stems + exports) | `Documents\Unweave` | `~/Music/Unweave` | **No** |
| Downloaded FFmpeg | `$INSTDIR` (beside the app) | `~/.local/share/unweave/app/` | Yes (Windows) |

Resolved in [`ui_entrypoint.py`](../../app/ui_entrypoint.py) (`writable_dirs()`) and
[`tools.py`](../../app/unweave/tools.py).

### Why models are not in the app folder

Deliberate, and the reason is documented in `ui_entrypoint.py`: writing to Program
Files needs admin rights that a plain double-click shortcut does not have, so config
and the multi-hundred-MB model cache go to per-user app data instead. The same
`writable_dirs()` handles the OneDrive-redirected Documents case via `known_folder()`.

## Measured footprint

Real numbers from a Linux install with four projects:

| Item | Size |
|---|---:|
| Model cache (`models/`) | **455 MB** |
| Projects (4 songs) | **1.3 GB** |
| — of which stems | ~1.1 GB |
| — of which originals | ~160 MB |
| Setup stack (torch, onnxruntime, librosa, yt-dlp) | ~1.3–1.8 GB |
| Embedded runtime (Windows) | ~38 MB |

Model cache contents, per file:

| File | Size | Loaded when |
|---|---:|---|
| `lead_rhythm_listra92.ckpt` | 337 MB | guitar split |
| `955717e8-8726e21a.th` (`htdemucs`) | 84 MB | 4-stem |
| `5c90dfd2-34c22ccb.th` (`htdemucs_6s`) | 55 MB | 6-stem (default) |

## The real risk: stem amplification, not cache

Cache is **bounded** — models are lazy, one-time, and finite (455 MB total, and the
app never re-downloads a validated file). The genuine growth is **projects**, because
canonical stems are stored as **44.1 kHz stereo 16-bit WAV = 10.1 MB per stem per
minute** — lossless, uncompressed.

Measured against a 3.7-minute song:

```
original.wav    21 MB
6 stems        187 MB      <- ~9x the original
```

A full 6-stem run on a 4-minute song is ~242 MB of stems. Worst case, a **guitar
split keeps everything**: the original guitar stem *plus* both halves:

```
guitar.wav      39.5 MB    <- kept, no longer needed once split
lead.wav        79.0 MB
rhythm.wav      79.0 MB
                          ~198 MB for one stem
```

So the ordering of concern is:

1. **Projects / stems** — unbounded, and grows ~9x per imported song. This is the only
   thing that meaningfully accumulates.
2. **Export copies** — every export writes *new* files into `exports/` and **nothing
   ever deletes old ones**. Re-exporting the same song in another format adds a full
   set; re-exporting the same format overwrites by filename. Repeatedly changing
   formats grows this without limit.
3. **Orphaned staging directories** — `.separation-*`, `.youtube-*`, `.import-*`,
   `.exports-*`, `.guitar-split-*`, `.stems-*`, `.model-download-*`. Normal runs clean
   these up (most use `TemporaryDirectory`), but an interrupted run leaves one behind
   and **nothing ever sweeps them**. See
   [06 — Close behavior](06-close-behavior.md).
4. **Upload buffer** — `/api/import` accepts up to **2 GB** per upload
   (`self.body_size(2 * 1024**3)`), streamed to a temp dir, then **copied** into the
   project via `import_project`. A single import therefore briefly needs ~2x the file
   size in free space.
5. **Cover images** — small, content-addressed (`cover-<sha256[:20]>`), and skipped
   when already present, so effectively bounded.

There is **no** cache size cap or eviction (the cache is bounded, so none is needed).
Jobs that write audio now check free space first; see the disk-space precheck below.

## Uninstall behavior

**Windows** (`installer/Unweave.nsis`, `Section "Uninstall"`) removes only:

- `$INSTDIR` contents (app, `unweave/`, `runtime/`, `launch.bat`, `ui_entrypoint.py`,
  docs, icon) and `$INSTDIR` itself
- Start Menu folder and the desktop shortcut
- The `HKLM` uninstall registry key

It **never touches** `%LOCALAPPDATA%\Unweave` (models + config) or
`Documents\Unweave` (projects). Consequence: uninstall then reinstall keeps
your ~455 MB of models and skips re-downloading. To fully clean up, the user must
delete `%LOCALAPPDATA%\Unweave` manually.

**Linux** (`installer/install-linux.sh --uninstall`) matches this intent: it removes
the prefix, launcher, `.desktop` entry, and icon, and prints the three preserved paths
so the user knows what remains. When `PREFIX` is the default
(`~/.local/share/unweave`, same folder as `CONFIG_DIR`), uninstall still keeps
`ui.json` in place (remove everything else under the prefix, then restore settings).
`--purge` removes models and `ui.json` after uninstall; projects are never touched.

## Planned change

1. **Switch canonical stem storage from WAV to FLAC** — done (see below). `combine_other()`
   keeps its float32 WAV intermediate; only the final stored stem is FLAC. `guitar_split.py`
   reads/writes FLAC via `soundfile`. Web player audio route serves `audio/flac` for `.flac`
   stems, `audio/wav` for legacy `.wav` stems. Backward compatible: existing `.wav` stems
   are still detected and played.
2. **Offer to delete the model cache on uninstall** — done on Windows (NSIS prompt;
   packages/ffmpeg/models/logs removal retries up to 5× with a 1 s pause for briefly
   locked files); Linux `--purge` removes models + settings and prints what went.
3. **Prune `guitar.wav` after a successful guitar split** — done implicitly: new projects
   store `guitar.flac` only when no split exists; once split into `lead.flac` + `rhythm.flac`,
   `guitar.flac` is excluded from the stem list. Legacy `guitar.wav` projects behave the same.
4. **Add a disk-space precheck** before a job — done (see below).
5. **Sweep stale staging directories at startup** — done in spec 06 (shared implementation:
   `Library.sweep_stale_staging()`, called at end of `Library.__init__`).
6. **Surface sizes in the UI** — done in the Settings panel (spec 12): model cache
   size, per-project totals, Clear models / Clear exports.
7. **Document the 9x amplification** in the README — done ("How much space songs take").

### Canonical stems: WAV → FLAC (done)

[03 — Output formats](03-output-formats.md) chose WAV as the canonical working format and
that reasoning still holds for *why not hand the separator MP3/FLAC directly* (guitar split
needs raw samples, `combine_other()` needs float headroom, playback needs a decodable file).
It does not rule out FLAC specifically: FLAC is lossless (bit-exact round trip, `soundfile`
decodes it natively) and compresses PCM audio to roughly 50–60% of WAV size.

Implemented:

- `pipeline.py`: `create_separator(output_format="FLAC")`; the separator matches its
  16-bit input, so these stems are bit-exact with the old WAVs. `combine_other()` mixes
  to float32 WAV then encodes to 24-bit FLAC before storing (FLAC has no float format).
- `guitar_split.py`: writes `lead.flac` / `rhythm.flac` via `soundfile` as 24-bit
  (`PCM_24`; soundfile would otherwise default to 16-bit); reads either format.
- `store.py`: stem detection matches both `.wav` and `.flac`; legacy `.wav` stems still
  listed and played.
- `library.py`: separation CLI output checked as `.flac`; guitar-split input is whichever
  of `guitar.flac` / `guitar.wav` exists (`store.stem_file()`).
- `server.py`: audio route serves `audio/flac` for `.flac` names, `audio/wav` otherwise.
- `web/js/audio/audio.js`: stem color lookup and guitar split button keyed on the stem name,
  ignoring `.flac` / `.wav`.

Expected reduction: **~40–50% off stem storage on every project**.

## Remaining work

- [x] FLAC plays in the pywebview `<audio>` element; FLAC stems have shipped.
- [x] Windows uninstall prompt: `Unweave.nsis` asks "Also delete the downloaded AI
      models (~500 MB) and app settings?" (default No; projects are never touched).
      Packages / FFmpeg / models / logs removal retries up to 5 times (Sleep 1000)
      when a file stays locked; one leftover-folder message if anything remains.
- [x] Linux `--purge` for `install-linux.sh`: uninstall plus
      `~/.cache/unweave/models` and `~/.local/share/unweave/ui.json`; never the
      music/projects folder; prints exactly what it removed.
- [x] Disk-space precheck (see below).
- [x] Decided: old exports are **not** replaced wholesale. Deleting files the user
      exported, without asking, is riskier than the growth; a per-project "Clear
      exports" action belongs in the cleanup UI below.
- [x] Per-project / total size display and selective cleanup in Settings
      ([12 — Settings panel](12-settings-panel.md)): `GET /api/storage`,
      `POST /api/storage/clear-models`, `POST /api/projects/<id>/clear-exports`.
- [x] Stem sizes documented in the README ("How much space songs take").

### Disk-space precheck (done)

`tools.require_free_space(path, needed)` refuses a job up front with a plain message
("Not enough disk space on C:\: this needs about 1.2 GB but only 300 MB is free. Free
up some space and try again.") instead of letting a full disk surface mid-job as an
FFmpeg or model error. It keeps 200 MB of headroom on top of the estimate. Sizes are
estimated from 16-bit PCM (`PCM_BYTES_PER_SECOND`), which over-asks a little for FLAC:

| Job | Drive checked | Estimate |
|---|---|---|
| Separation | project | duration × PCM × 6 stems (+3 with the guitar split: two 24-bit leaves) |
| Separation | system temp | duration × PCM (the normalized `input.wav`) |
| Guitar split only | project | current stems folder (copied into staging) + duration × PCM × 3 |
| Export | project | chosen stems' bytes × per-format factor (`EXPORT_SIZE_FACTOR`: PCM 2.0, FLAC 1.0, lossy 0.2–0.3) |
| Import upload | system temp and projects root | upload size |

Duration honours the trim. Separation and export check again when the job actually
starts, because queued jobs ahead of it may have used the space. A refused upload is
read off the socket before answering, so the webview shows the message rather than a
reset connection. YouTube imports are not prechecked (size unknown until download).

## Constraints

- Do not move the model cache into `$INSTDIR`; the per-user location is a confirmed
  fix for the Program Files write-permission problem.
- Do not change `writable_dirs()` / `known_folder()`; the OneDrive-aware behavior is a
  confirmed fix.
- Any cleanup must be conservative: known prefixes only, never follow symlinks, never
  delete outside the projects root, and never delete data the user did not create
  through the app.

## Related

- [04 — First-run setup](04-first-run-setup.md) — what gets downloaded and when.
- [06 — Close behavior](06-close-behavior.md) — orphaned staging directories.
- [03 — Output formats](03-output-formats.md) — the export matrix that writes `exports/`.
