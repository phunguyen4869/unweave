# 03 — Export stems in other output formats

Status: Done

What this covers: on-demand copies of canonical WAV stems into common delivery formats without changing the working stems.

**Related:** [02 — Pre-separation trim](02-pre-separation-trim.md), [App specification](01-app.md), [Architecture](../architecture.md)

### Implementation status

- [x] Export job, cancellable FFmpeg conversions, staging, and manifest.
- [x] Export API/CLI contract and safe exports-folder reveal.
- [x] Export dialog, progress, and acceptance checks.

## 1. Problem

Every stem the app produces is a WAV file in `<project>/stems/`, and there is no
export step. Users who want MP3 for a phone, FLAC for an archive, or M4A for a
DAW have to convert the files themselves.

The WAV choice is not arbitrary:

- `pipeline.separate()` asks audio-separator for `output_format="WAV"`.
- `pipeline.combine_other()` mixes in **float** WAV specifically so summed stems
  can exceed 0 dBFS without clipping or gain changes.
- `guitar_split.split_guitar()` requires a 44.1 kHz stereo WAV input and writes
  float WAV output.
- The web player decodes the same `stems/*.wav` files for playback and A/B
  against the original.

## 2. Decision

Keep WAV as the canonical working format and add an **on-demand export** that
transcodes copies into `<project>/exports/`.

Rejected alternatives:

| Alternative | Why not |
|---|---|
| Ask audio-separator for MP3/FLAC directly | Guitar split still needs WAV; playback needs decodable files; `combine_other` relies on float WAV. |
| Convert `stems/` in place | Destroys the lossless source, breaks guitar split, stacks generation loss on every re-export. |
| Export the original recording too | Out of scope for this pass; the original is already a normal file in the project folder. |

**Revisit (see [07 — Disk usage](07-disk-usage.md)):** "canonical format" above
means *not re-encoded to a lossy format*, not "must be the WAV container." FLAC is
lossless and ~40–50% smaller than WAV for the same PCM data, so switching the
canonical container to FLAC does not conflict with this decision — only the
rejected alternatives (asking the separator for lossy output, or converting
`stems/` to a lossy format in place) are ruled out here.

## 3. User-facing behaviour

- A new **Export** button in the song header, next to *Open folder* / *Edit* /
  *Delete*. Disabled when the project has no stems, or while any job runs.
- Clicking it opens an **Export stems** dialog:
  - **Formats** — checkboxes. FLAC is checked by default; MP3 320 and the rest
    are opt-in.
  - **Stems** — checkbox per current stem, all checked by default. Uses
    `project.stems` (so lead/rhythm appear when the guitar has been split).
  - **Prevent clipping** — checked by default. See §4.3.
  - Destination is fixed: `<project>/exports/`. The dialog says existing files
    of the same name will be replaced.
  - Primary button: **Export**.
- Export runs as a normal background job (same panel, progress, cancel button,
  log) and can be cancelled.
- On success: notice “Exported N stems as FLAC, MP3”, and the dialog offers
  **Open exports folder**.
- Existing exports are replaced per file only after every requested conversion
  succeeds (see §6.3).

## 4. Format matrix

All exports are 44.1 kHz stereo, matching the stored stems. Do **not** offer
48 kHz: the pipeline already resampled to 44.1 kHz, so 48 kHz would only
upsample.

| id | Extension | FFmpeg codec args | Notes |
|---|---|---|---|
| `flac` | `.flac` | `-c:a flac -compression_level 5` | Lossless, roughly 50–60% of WAV size. Default. |
| `mp3` | `.mp3` | `-c:a libmp3lame -b:a 320k` | Universal compatibility. |
| `opus` | `.opus` | `-c:a libopus -b:a 192k` | Best quality per byte; not read by every DAW. |
| `m4a` | `.m4a` | `-c:a aac -b:a 256k -movflags +faststart` | Apple ecosystem. |
| `wav16` | `.wav` | `-c:a pcm_s16le` | DAW-safe, smallest WAV. |
| `aiff` | `.aiff` | `-c:a pcm_s16be` | Optional; same size as WAV, some hardware/DAW workflows. |

The bundled FFmpeg (gyan.dev *essentials*) includes `libmp3lame`, `libopus`,
native `flac`, and native `aac`, so no extra download is needed.

### 4.1 Command shape

```
ffmpeg -nostdin -hide_banner -loglevel error -y \
  -i <project>/stems/<stem>.wav \
  -map_metadata -1 \
  -metadata title="<title> — <stem label>" \
  -metadata artist="<artist>" -metadata album="<album>" -metadata date="<year>" \
  [-af alimiter=limit=0.891:level=0:latency=1] \
  <codec args> <project>/exports/<stem>.<ext>
```

- Metadata comes from `metadata.json`; empty fields are omitted.
- The stem label is the display name already computed by `describe_project`
  (e.g. “Lead”, “Guitar remainder”), not the raw filename.

### 4.2 Sample format

`normalize()` writes 16-bit PCM, but `other.wav` (when it folds several stems
together) and `lead/rhythm.wav` are float WAV and can exceed full scale by
design. FLAC/MP3/AAC cannot store samples above 0 dBFS, so §4.3 is not optional
for those stems.

### 4.3 Prevent clipping

Default filter:

```
alimiter=limit=0.891:level=0:latency=1
```

`limit=0.891` is ≈ −1 dBFS. `level=0` is important: FFmpeg’s `alimiter`
auto-levels by default, which would boost quiet stems. With `level=0` it only
attenuates peaks above the limit. `latency=1` compensates the limiter’s short
delay so exports stay aligned with the unprocessed stems.

If the user unchecks the option, show a one-line warning in the dialog:
“Stems that peak above full scale will clip in lossy formats.”

## 5. API contract

### `POST /api/projects/{id}/export`

```json
{
  "root": "/path/to/projects",
  "formats": ["flac", "mp3"],
  "stems": ["vocals.wav", "guitar.wav"],
  "prevent_clipping": true
}
```

Response: the job object, same shape as `/separate`.

### CLI equivalent

When exposed from the CLI, the export command accepts the same project, format list, stem subset, and clipping preference as the API. It writes to that project's `exports/` directory, reports conversion progress, and treats interruption as cancellation; it must use the same staging and replacement rules below.

Validation (400 on failure):

- `root` matches the current library root (`require_matching_root`).
- No other job is running.
- `formats` is a non-empty list of known ids, de-duplicated.
- `stems` is a non-empty subset of the project’s current stem filenames.
- Every source is a regular file, not a symlink.
- `exports/` either does not exist or is a real directory, not a symlink.
- Output paths pass `output_files.validate_outputs()` (no symlink, not a
  directory, not the source).

### Reveal

Extend the existing reveal route:

```json
{"root": "...", "target": "exports"}
```

Allowed targets: `project` (default), `stems`, `exports`. `exports` is only
valid when the directory exists. The route must not accept arbitrary paths.

## 6. Backend design

### 6.1 `audio/exports.py`

```python
FORMATS = {
    "flac":  {"extension": ".flac", "args": ["-c:a", "flac", "-compression_level", "5"]},
    "mp3":   {"extension": ".mp3",  "args": ["-c:a", "libmp3lame", "-b:a", "320k"]},
    "opus":  {"extension": ".opus", "args": ["-c:a", "libopus", "-b:a", "192k"]},
    "m4a":   {"extension": ".m4a",  "args": ["-c:a", "aac", "-b:a", "256k", "-movflags", "+faststart"]},
    "wav16": {"extension": ".wav",  "args": ["-c:a", "pcm_s16le"]},
    "aiff":  {"extension": ".aiff", "args": ["-c:a", "pcm_s16be"]},
}

def export_stems(project, stems, formats, prevent_clipping, report) -> list[Path]:
    ...
```

`report(completed, total, label)` is the progress callback used by `Library`;
`exports.py` stays UI-free.

Responsibilities:

1. Re-read `describe_project(project)` and map `stems` filenames to display
   names + `offset` (see trim spec).
2. `total = len(stems) * len(formats)`; iterate stems × formats.
3. For each output, run FFmpeg with `-progress pipe:1 -nostats` and parse
   `out_time_us` to compute the fraction of that file. Report
   `(completed + fraction) / total`.
4. Write a `manifest.json` next to the exports:

```json
{
  "exported_at": "2026-10-26T12:00:00Z",
  "formats": ["flac", "mp3"],
  "prevent_clipping": true,
  "files": [
    {"stem": "vocals.wav", "label": "Vocals", "output": "vocals.flac", "offset": 90.0},
    {"stem": "lead.wav", "label": "Lead", "output": "lead.flac", "offset": 95.0}
  ]
}
```

`offset` is copied from the stem’s `describe_project()` entry so a later
listener knows the export is a section (see
[02 — Pre-separation trim](02-pre-separation-trim.md)).

### 6.2 `Library.start_export()`

New method on `JobQueueMixin` in `webui/queue.py`, modelled on `start()`:

- Sets `self.job = {"kind": "export", "project": id, "formats": [...],
  "stems": [...], "phase": "prepare", "progress": 0, ...}`.
- Worker thread calls `export_stems()`.
- On success: `status="succeeded"`, `progress=100`, `phase="done"`.
- On failure: `status="failed"`, `error=str(error)`.
- On cancel: reuse `Library.cancel()`; the worker discards the staging
  directory and leaves previous exports untouched.

### 6.3 Staging and replacement

- Create `tempfile.TemporaryDirectory(prefix=".exports-", dir=project)`.
- Convert every requested file into that directory. If any conversion fails,
  delete the staging directory and leave `<project>/exports/` exactly as it was.
- After all conversions succeed, create `exports/` if needed and `os.replace()`
  each staged file onto its destination. Then write `manifest.json`.
- Replacing the whole `exports/` directory is *not* used: exporting only two
  stems must not delete previously exported stems.

## 7. Job progress and UI

- `progress.track_progress()` / `Library._track_progress()` gains markers:
  - `"Exporting stems"` → phase `export`, floor 2.
  - `"Exported "` → phase `finalize`, floor 96.
  - Per-file lines such as `"Exporting vocals.flac (3/12)"` are hidden from the
    log and drive the phase.
- `web/js/features/progress.js` and `web/js/views/song.js`:
  - New `EXPORT_STEPS = [['prepare', 'Check files'], ['export', 'Convert stems'],
    ['finalize', 'Write files']]`.
  - `renderProgress()` treats `job.kind === 'export'` like the separation branch,
    with titles: prepare “Preparing export”, export “Converting stems”,
    finalize “Writing exports”; sub “Lossless and lossy copies stay inside this
    project”.
  - `job.stems` count still displays the number of stems.
  - Ended labels: succeeded “Export complete”, failed “Export failed”.
- The export dialog is disabled while `jobRunning()` is true, and the song
  header button reflects the same state.

## 8. Edge cases

| Case | Behaviour |
|---|---|
| Project has stems but one is a symlink | Reject with the same wording used by separation. |
| `exports/` is a symlink | Reject. |
| User exports `lead.wav` and `rhythm.wav` | Allowed; they are normal stems. |
| User exports the same format twice | De-duplicate formats. |
| Disk full mid-export | FFmpeg fails → job failed → staging removed, old exports intact. |
| Export while separation is running | Blocked by the single-job rule. |
| Project deleted | `shutil.rmtree(project)` removes `exports/` too. |
| Very long song | Progress stays determinate; no HTTP timeout because the work runs in the job thread. |
| FFmpeg missing | The existing `ensure_ffmpeg_on_path()` gate in the route returns `MISSING_FFMPEG`. |

## 9. Acceptance criteria

1. A project with six WAV stems can export FLAC and MP3; `exports/` contains
   six `.flac` and six `.mp3` files, each playable and the same duration as its
   source.
2. Exporting a subset replaces only those files; other exports remain.
3. A deliberately hot stem (float WAV above 0 dBFS) does not clip with
   *Prevent clipping* on; unchecking it warns in the dialog.
4. Export progress advances per file and the cancel button stops FFmpeg within
   a few seconds; no partial files appear in `exports/`.
5. No change is needed in `describe_project()` for exports: `exports/` is a
   directory, so it is not mistaken for an original recording.
6. The manifest records formats, stems, clipping setting, and each stem’s
   offset.
7. Old projects without `exports/` behave exactly as before.

## 10. Out of scope

- Changing the stored stem format.
- Sample-rate or bit-depth choices beyond 16-bit WAV.
- EBU R128 / loudness normalisation.
- Batch export across multiple projects.
- Exporting the original recording.

## 11. Implementation paths

| File | Change |
|---|---|
| `audio/exports.py` | New module: format table, FFmpeg invocation, manifest, staging. |
| `webui/queue.py` | `start_export()`, job state; progress markers in `progress.py`. |
| `webui/routes/projects.py` | `/export` route, validation, reveal target. |
| `web/js/views/song.js` | Export dialog, submit, export job rendering, reveal target. |
| `web/css/song.css` (or closest target stylesheet) | Dialog layout, format grid. |
| CLI entry point | Optional export command and arguments. |
| Tests | See acceptance criteria; add unit tests for the format table and staging. |
