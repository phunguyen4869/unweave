# 02 — Pre-separation trim (overall and guitar)

Status: Done

What this covers: non-destructive section selection before overall separation and guitar lead/rhythm splitting, with section-only playback.

**Related:** [03 — Output formats](03-output-formats.md), [App specification](01-app.md), [Architecture](../architecture.md)

### Implementation status

- [x] Backend trim validation, normalization, persistence, and guitar slicing.
- [x] CLI/API trim arguments and project stem offsets.
- [x] Offset-aware playback and trim editors in New and Song views.
- [x] Automated acceptance checks and export-manifest integration.

## 1. Problem

Separation processes the whole recording. On a 6-minute song the Demucs pass
takes minutes on CPU, and the guitar lead/rhythm RoFormer pass is slower still.
Users who only care about a solo, a chorus, or a riff have no way to process
just that section.

## 2. Decision

Add a **non-destructive trim** that limits what the model sees:

- The project keeps the **full original recording** on disk.
- The selected range is processed; the resulting stems contain only that range.
- The trim is stored in `separation.json`.
- Playback presents only the selected section; the original and trimmed stems
  start together at the section start for A/B listening.
- Re-separation always reads the full original; the last trim is pre-filled but
  can be cleared.

No silence padding, no destructive edit of the original.

### Why not trim the stored original

It would make playback trivial but lose the rest of the song, make “separate
again” impossible, and surprise users who expect a range selection to be
reversible. The offset approach costs one small player change and keeps the
project honest.

### Why not pad stems with silence

Padding would keep the timeline but throw away the storage and export benefit,
and WAV silence is not free. Offsets are cheaper and exact.

## 3. Semantics

- For overall separation, `[start, end)` is measured in seconds on the
  **original recording** timeline.
- For guitar split, the user selects a range on the **stored `guitar.wav`**
  timeline. The backend converts it to the original timeline for storage.
- A trimmed stem file starts at its own `t = 0`, which corresponds to the
  absolute `start` on the project timeline.
- Stems from one separation run always share the same range.
- `lead.wav` / `rhythm.wav` may have a different range from the main stems.
- The original is never modified, and `describe_project()["original"]` is
  unchanged.

## 4. Data model

`stems/separation.json` gains optional `trim` objects:

```json
{
  "stems": ["vocals", "guitar", "bass", "drums", "piano", "other"],
  "trim": {"start": 90.0, "end": 120.0},
  "lead_rhythm_split": {
    "model": "listra92",
    "sha256": "b3c47bca…",
    "overlap": 0.5,
    "trim": {"start": 95.0, "end": 110.0}
  }
}
```

Rules:

- `trim.start` / `trim.end` are finite numbers, `0 <= start < end`.
- Missing `trim` means “full recording”, exactly like today.
- `separation.trim` applies to every stem in `stems/` except `lead.wav` and
  `rhythm.wav`.
- `lead_rhythm_split.trim` applies to `lead.wav` and `rhythm.wav` and is stored
  in **absolute** project time (not relative to `guitar.wav`).
- A malformed trim must never break the library. `describe_project()` drops
  the invalid `trim` keys from the returned `separation` dict, keeps the old
  behaviour (offset 0), and appends a warning:
  `"Separation settings: invalid trim range."` Dropping the keys matters
  because the frontend echoes `separation.trim` back when re-separating.

### 4.1 `describe_project()` change

Every stem dict gains an `offset` (seconds, default `0`):

```python
{"name": "Vocals", "file": "vocals.wav", "bytes": 123, "version": 456,
 "offset": 90.0}
```

Mapping:

- Any stem produced by the guitar split (`lead.wav`, `rhythm.wav`, and the
  legacy `guitar-target-*` / `guitar-remainder` names) →
  `lead_rhythm_split.trim.start` if present, else 0.
- everything else → `separation.trim.start` if present, else 0.
- The original track has no offset (0).

`separation` is already returned to the frontend, so no extra top-level field
is needed. `list_projects()` picks this up automatically.

## 5. Backend

### 5.1 `audio.pipeline.normalize(source, destination, trim=None)`

```python
def normalize(source, destination, trim=None):
    args = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    if trim:
        start, end = trim
        args += ["-ss", f"{start:.6f}"]
    args += ["-i", str(source)]
    if trim:
        args += ["-t", f"{end - start:.6f}"]
    args += ["-map", "0:a:0", "-vn", "-ar", "44100", "-ac", "2",
             "-c:a", "pcm_s16le", str(destination)]
```

- `-ss` before `-i` with FFmpeg’s default accurate seek is sample-accurate
  while still skipping most of the file.
- `-t` (output duration) avoids ambiguity about whether `-to` is relative to
  the seek point.
- Add a 5 ms fade in/out when trimming to avoid clicks at hard cuts:
  `-af "afade=t=in:st=0:d=0.005,afade=t=out:st=<dur-0.005>:d=0.005"`.
  Skip the fade when the range reaches the file boundary.

### 5.2 Duration validation

New helper in `audio/pipeline.py`:

```python
def probe_duration(path: Path) -> float:
    # ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1
```

Validation, both in `pipeline.separate()` and in `Library.start()` (so the UI
gets a friendly 400 instead of a failed job):

- `trim` is either `None` or a pair of finite numbers.
- `0 <= start < end`.
- `end <= duration + 0.05`.
- `end - start >= 1.0` for overall separation, `>= 2.0` for guitar split
  (the RoFormer chunk is 3 s and very short inputs give poor output).
- Round to 3 decimals before persisting.

### 5.3 `audio.pipeline.separate(..., trim=None)`

- Pass `trim` to `normalize()`.
- Persist `settings["trim"] = {"start": start, "end": end}` only when a trim is
  present. A full-length run must overwrite `separation.json` **without** the
  key, so clearing a trim restores full-length stems cleanly.
- `combine_other()` needs no change: all model outputs already share the
  trimmed length.
- Model selection, output naming, staging, and `validate_outputs()` are
  unchanged.

### 5.4 `audio.guitar_split.split_guitar(..., trim=None)`

- Read `separation.json` first (already done) to learn the guitar stem’s own
  offset. Guard against a missing or malformed value:
  `saved = settings.get("trim"); base = saved.get("start", 0) if isinstance(saved, dict) else 0`.
- Slice at read time instead of reading the whole file:

```python
info = sf.info(source)
sr = info.samplerate
start_frame = round(local_start * sr)
frames = round((local_end - local_start) * sr)
mix, sr = sf.read(source, dtype="float32", always_2d=True,
                  start=start_frame, frames=frames)
```

- Apply a 5 ms fade in/out in NumPy on the slice.
- Keep the existing chunking, padding, overlap-add, and float WAV output.
- Persist the absolute range:

```python
settings["lead_rhythm_split"]["trim"] = {
    "start": round(base + local_start, 3),
    "end": round(base + local_end, 3),
}
```

- No trim → no `trim` key (old behaviour).

### 5.5 CLI

Add to both `separate` and `split-guitar`:

```
--start FLOAT   Start of the section in seconds (requires --end)
--end FLOAT     End of the section in seconds (requires --start)
```

Both-or-neither; passing one is an error. `--start`/`--end` are relative to the
input file (`--file` or `--youtube` for `separate`, `guitar.wav` for
`split-guitar`).

### 5.6 `Library.start()` and routes

`Library.start(identifier, preset, stems=None, *, guitar_split=False,
trim=None)`:

- Normalise/validate `trim` as in §5.2.
- For overall separation, probe `project / info["original"]`.
- For guitar split, probe `project / "stems" / "guitar.wav"`.
- Append `--start` / `--end` to the CLI command.
- Keep the existing “guitar must exist / no lead or rhythm yet” checks.

Request bodies:

```json
// POST /api/projects/{id}/separate
{"root": "...", "preset": "custom", "stems": ["vocals"],
 "trim": {"start": 90.0, "end": 120.0}}

// POST /api/projects/{id}/split-guitar
{"root": "...", "trim": {"start": 5.0, "end": 25.0}}
```

`trim` is optional; `null` or absent means the full file. The split-guitar trim
is **relative to `guitar.wav`**, as in §5.4.

## 6. Section-only playback

### 6.1 `web/js/audio/audio.js`

- `describe_project()` offsets remain absolute project time.
- When `separation.trim` is valid and the original is loaded, the player converts
  the project to section time: `sectionStart` / `sectionEnd` come from the trim,
  and the transport duration is `sectionEnd - sectionStart`.
- The original track gets `offset = 0` and `bufferOffset = sectionStart`; each
  stem gets `offset = max(0, stem.offset - sectionStart)` and
  `bufferOffset = 0`. `track.projectOffset` keeps the absolute offset for UI
  labels and exports.
- `setTracks(tracks, duration)` uses the explicit section duration. Scheduling
  starts each source at its `bufferOffset`, caps it at the section boundary, and
  `onended` compares the track’s effective end with the section end.
- `renderTracks()` draws the original waveform from `bufferOffset` for the
  section length, so the original preview matches what is heard.
- `restart` and `seek` are section-relative: 0 is the start of the selected
  range, not the start of the original file.

### 6.2 `web/js/views/song.js` and shared app state

- `buildLoadItems()` still carries absolute offsets; `audio.js` normalizes them
  and preserves `projectOffset` for the trim editor, split dialog, and export
  note.
- The status line reads `Playing section 0:00 – 2:07.6 (127.6 s)`.
- `audioSignature` still includes absolute stem offsets, so changing trim
  reloads audio.

## 7. Trim UI

The visual design belongs to the designer; these are the required behaviours.
The interaction is implemented in `web/js/views/new.js` and
`web/js/views/song.js`; shared transport scheduling is in `web/js/audio/audio.js`.

### 7.1 Overall separation

- A **Trim section** control in the *Separate / Separate again* panel. It is
  available whenever the project has an original, including before any stems
  exist.
- Opens an inline editor with a wide waveform of the original (reuse the
  already-decoded `AudioBuffer` when available; otherwise load it with the
  existing progress UI).
- Selection:
  - Two draggable handles and a draggable region between them.
  - Dimmed audio outside the selection, accent-tinted inside.
  - Start/end readouts in `m:ss.mmm`, plus a selection-length readout.
  - Numeric start/end inputs for precise entry.
  - Keyboard: focusable handles, ←/→ = 0.1 s, Shift+←/→ = 1 s, Home/End =
    file bounds.
  - Snap to 10 ms; clamp to `[0, duration]`; keep `start < end`.
  - **Full song** resets to `0 … duration`.
- **Preview** plays from the start handle and pauses automatically at the end
  handle. This can live in `animate()` as a UI-side check; no player change
  needed.
- The panel shows a chip when a range is active:
  `Section 1:30.0 – 2:00.0 (30.0 s)` with a **Clear** action.
- Starting a separation sends `trim`. If the range is the full song, omit it.
- On success the chip is restored from `separation.trim`, and the player seeks
  to the section start.
- When reopening a project that already has a trim, the editor is pre-filled
  with the stored range.

### 7.2 Guitar split

- The split button on the guitar track currently fires immediately. Change it
  to open a small **Split guitar** dialog:
  - Mini waveform of `guitar.wav`, same handle behaviour as §7.1.
  - Default range: full file.
  - Times are displayed in **project time** (`guitar offset + local`) but the
    request sends local seconds, matching §5.4.
  - Primary button: **Split into lead & rhythm**.
- If the guitar stem is already trimmed, the dialog’s full range is that
  trimmed file, and the stored `lead_rhythm_split.trim` becomes
  `guitar_offset + local`.
- Keep the existing guard: refuse when `lead.wav`/`rhythm.wav` already exist.

### 7.3 Accessibility

- Handles expose `role="slider"` with `aria-valuemin`, `aria-valuemax`,
  `aria-valuenow`, `aria-valuetext` (“1 minute 30 seconds”).
- Numeric inputs have visible labels.
- The dimmed region is decorative; state is conveyed by the readouts and
  values.

### 7.4 First separation of a new file

The New view currently uploads the file and immediately calls `/separate`
from `web/js/views/new.js`. To make trim available on the **first**
separation, not only on “Separate again”:

- After a file is chosen, decode it locally with the existing `AudioContext`
  and show the same trim editor (waveform, handles, numeric fields) in the
  New view.
- Include `trim` in the `/separate` call that follows the upload:
  `{root, ...choice, trim}`.
- Numeric start/end fields remain usable when the browser cannot decode the
  file or when it is very long; the waveform is an enhancement, not a
  requirement.
- YouTube import is the exception: its duration is unknown until the download
  finishes, and the import job auto-continues into separation. The first
  YouTube separation runs full-length; the user can trim it afterwards with
  “Separate again”. Document this in the hint text rather than blocking the
  import.

## 8. Interaction with export

- Export reads the stored stems, so exports contain only the trimmed section.
- `exports/manifest.json` records each stem’s `offset` (see
  [03 — Output formats](03-output-formats.md) §6.1).
- The export dialog shows a line when the stems are a section:
  `These stems are a 30.0 s section starting at 1:30.0.`

## 9. Edge cases

| Case | Behaviour |
|---|---|
| Trim reaches the exact end of the file | Allowed; `end <= duration + 0.05`. |
| `start >= end` | 400 with “Choose a section longer than 1 second.” |
| Section shorter than 1 s | Rejected. Guitar split requires 2 s. |
| Non-finite / string values | Rejected. |
| Trim on a YouTube-sourced project | Not available during the first import; applied afterwards with “Separate again”. Original stays full. |
| Old project without `trim` | Offset 0, unchanged playback. |
| Malformed trim in `separation.json` | Ignored, warning shown, playback at offset 0. |
| Re-separation with trim cleared | `separation.json` is rewritten without `trim`; stems become full length; offsets return to 0. |
| Re-separation with a different trim | Old stems replaced atomically; new trim stored. |
| Guitar split after a trimmed separation | `guitar.wav` is already a section; local range is within it; stored range is `guitar_offset + local`. |
| Guitar split before any trim | `base = 0`; behaves like today. |
| Cancel during a trimmed job | Existing cancellation path; staged stems discarded. |
| Seek before the section | Stems are silent, original plays; correct. |
| Export while a trim is active | Exports only the section. |

## 10. Acceptance criteria

1. Separating 1:30–2:00 produces stems that are 30 s long, and playback starts
   at 1:30 with the original aligned; seeking to 0:30 plays the original alone.
2. Clearing the trim and separating again produces full-length stems and
   removes `trim` from `separation.json`.
3. `describe_project()` returns `offset: 90.0` on each stem for that project,
   and `0` for untrimmed projects.
4. Splitting a trimmed guitar at a sub-range stores an absolute
   `lead_rhythm_split.trim`, and lead/rhythm play at the right place.
5. The model receives only the section: a 30 s selection finishes much faster
   than the full song, and the log still shows `Preparing audio` →
   `Separating with …` → `Writing stems`.
6. A 0.5 s selection is rejected with a clear message.
7. Old projects load and play exactly as before.
8. Export of a trimmed project contains the section only, and its manifest
   records the range.

## 11. Out of scope

- Trimming the stored original.
- Loop regions, markers, or multiple sections per project.
- Waveform zoom / scrubbing beyond the existing seek bar.
- Automatic silence/onset detection.
- Crossfades longer than the 5 ms click guard.

## 12. Implementation paths

| File | Change |
|---|---|
| `audio/pipeline.py` | `probe_duration()`, `normalize(trim)`, `separate(trim)`, persist trim. |
| `audio/guitar_split.py` | Sliced `sf.read`, fades, absolute trim persistence. |
| CLI entry point | `--start` / `--end` on both commands. |
| `projects/store.py` | Validate trim, add `offset` to stem dicts. |
| `webui/queue.py` | `start(trim=...)`, validation, CLI args, job handling (`JobQueueMixin`). |
| `webui/routes/projects.py` | Trim on `POST …/separate` and `…/split-guitar`. |
| `web/js/audio/audio.js` | Per-track offset scheduling. |
| `web/js/views/new.js` | First-separation trim editor and request body. |
| `web/js/views/song.js` | Re-separation/split trim UI, seek-to-section, status line. |
| `web/css/song.css` (or closest target stylesheet) | Selection overlay, handles, dialog. |
| Tests | Trim math, offsets, project description, CLI parsing, export interaction. |
