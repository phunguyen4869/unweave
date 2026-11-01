# 09 — Job progress and ETA (time-weighted)

Status: Done

What this covers: how overall job percent and whole-job ETA are derived for separation
(especially advanced plans that also split guitar), how the detail panel shows
**step-first** numbers, and the soft plan warning when lead/rhythm split is enabled.

## Problem this solves

A dual-pass job (Demucs stems, then RoFormer lead/rhythm) used **fixed overall bands**
Demucs **12→70** / guitar **70→95**. Guitar is only *roughly* ~10× the stem pass
([architecture timing table](../architecture.md)), so those bands were neither stem
count nor wall-clock. Typical symptom: queue/nav showed ~77% while the ring showed
~30% of the second pass and most real time remained.

Prepare/load floors also climbed to **12%**, more bar than those steps usually deserve
on a warm run.

Separately, the detail panel mixed three scales without labels (ring = step %, line
bar / pill = whole job %, TIME LEFT = whole-job ETA including the guitar prior). Users
read every number as phase-local because the title is phase-local.

## Progress fields

| Field | Consumers | Meaning |
|---|---|---|
| `progress` | Nav pill, job queue bar, library badge, detail “Whole job” line | Overall 0–100 for the **whole job**, wall-clock oriented |
| `eta` / `eta_at` | Whole-job note under the line bar (`Done in about …`); not the hero timer | Whole-job remaining seconds (+ finalize fudge) |
| `eta_estimated` | Detail note under the line bar | `true` while the guitar prior still pads `eta` (stems pass, or cold guitar clock) |
| `step_progress` | Detail ring and active step chip | Current step’s own 0–100 (resets for `separate` / `guitar` / …) |
| `step_eta` / `step_eta_at` | Detail “Step time left” | Pass-local remaining (no finalize fudge) |
| `pass_count` / `pass_index` | Ring caption `Step N of M` | `2` / `1→2` when `split_leaves`; otherwise `1` / `1` |

Phases come from CLI markers (`Preparing audio`, `Separating with…`, `Splitting guitar`,
`Writing stems`, …) parsed in [`webui/library.py`](../../app/unweave/webui/library.py)
`_track_progress`. The ring must stay pass-local so a long guitar pass does not look
like a stalled stem pass.

## Detail panel layout (step-first)

Top half is current-step only; whole-job sits on one labelled line underneath:

```
 ┌────────┐  Separating stems                      [Cancel]
 │  18%   │  Pulling the mix apart into stems…
 │ Step   │
 │ 1 of 2 │  STEP TIME LEFT   ELAPSED    STEMS
 └────────┘  ~2m 40s          53s        4

             Whole job ▓▓░░░░░░░░░░░░░░░░░░  6%
             Split guitar runs next and takes longer

 Prepare → Load → [Separate 18%] → Split guitar → Save
```

Note under the bar:

- Dual-pass stems pass (`eta_estimated`): `Split guitar runs next and takes longer`
  (no whole-job minutes — those are the guessed prior).
- Dual-pass with a measured estimate: `Done in about {time}` from `eta` / `eta_at`.
- Single-pass (`pass_count === 1`): hide the note and the ring caption.

Implemented in [`progress.js`](../../app/unweave/web/js/features/progress.js); strings in
[`i18n.js`](../../app/unweave/web/js/core/i18n.js).

## Current behavior (time-weighted overall)

### Early floors and inference band

Warm-run floors (approximate):

| Marker | Phase | Floor |
|---|---|---:|
| Preparing audio | prepare | 1 |
| Loading model / Downloading … | load / download | 3 |
| Separating with… / Splitting guitar | separate / guitar | 5 |
| Writing stems / Exported … | finalize | 96 |

Inference samples map into **`SEPARATE_RANGE = (5, 95)`**. Finalize still jumps to ~96
before success pins 100.

### Mapping rule

On each Demucs tqdm or `Guitar split N%` line:

1. Update `step_progress` from the pass percent.
2. Compute pass-local remaining (tqdm ETA, or `spent × (100 − pct) / pct`).
3. Set `step_eta` to that pass-local remaining (no finalize fudge).
4. Build **job-level** remaining and overall `%`:

| Situation | `done` / `left` for overall `%` | `job.eta` | `eta_estimated` |
|---|---|---|---|
| Demucs, **no** guitar split | Demucs elapsed / Demucs remaining | remaining + finalize fudge (~3 s) | false |
| Demucs, guitar still queued | Demucs elapsed / (Demucs remaining + **prior** guitar) | same + finalize | true |
| Guitar running (clock warm, ≥ ~1 s spent) | measured Demucs duration + guitar elapsed / live guitar remaining | guitar remaining + finalize | false |
| Guitar just started (spent ≈ 0) | prior from `demucs_elapsed × GUITAR_TIME_RATIO` × pass % | prior remaining + finalize | true |
| Split-only (no Demucs) | guitar elapsed / remaining over the full inference band | no Demucs prior | false |

**Prior:** `GUITAR_TIME_RATIO = 10` — estimate only for the **not-yet-started** (or
cold-clock) guitar pass. It is **not** a claim that every track is exactly 10:1.
Once the guitar pass has usable wall time, this run’s measured Demucs:guitar timing
owns the bar and ETA.

Overall:

`progress = low + (high − low) × done / (done + left)` (monotonic; last inference pass
at 100% pins to `high` before finalize).

Tqdm’s bracket elapsed is preferred over wall clock when present so tests and bursty
UI updates stay stable.

### Advanced-plan warning

Cost chips (`~10×`) and the footer `≈ 11× a plain separation` already exist in the
plan dialog. When lead/rhythm split is on, `#plan-warning` also shows a soft
`plan.warn.splitSlow` note (en/vi). It does **not** modal or disable Start (only a
silent/empty plan disables confirm).

Implemented in [`plan-model.js`](../../app/unweave/web/js/features/plan-model.js)
`warnings()` and [`i18n.js`](../../app/unweave/web/js/core/i18n.js).

## Implementation checklist

- [x] Replace fixed Demucs/guitar overall bands with elapsed/(elapsed+ETA) mapping into `SEPARATE_RANGE`.
- [x] `GUITAR_TIME_RATIO` prior only while guitar is queued / clock cold; live guitar ETA afterward.
- [x] Shrink prepare/load floors; inference starts near 5%.
- [x] Keep `step_progress` / ring pass-local.
- [x] Dual-pass Demucs-phase ETA includes projected guitar time.
- [x] Soft `splitSlow` plan warning when split is enabled.
- [x] Progress-tracking unit tests in `tests/test_job_queue.py`.
- [x] Architecture note for the two meters + hybrid weighting.
- [x] Detail panel step-first UX: `step_eta`, `eta_estimated`, `pass_index` / `pass_count`, “Whole job” line + note.

## Out of scope / not done here

- Learning the ratio from past jobs or calibrating per GPU.
- Absolute minute estimates in the plan dialog from track length.
- Special download-phase weighting for cold model fetches (download still uses the early floor).
- Concentric dual rings (rejected: guitar arc would dominate ~10× and reintroduce the stalled feel).

## Constraints

- Do not drive the detail ring from overall `progress` — a long second pass must restart
  its own 0–100.
- Do not reintroduce fixed dual-pass bands (e.g. 12→70 / 70→95) as the source of truth
  for queue/nav percent.
- Progress must never go backwards within a job.
- Prefer relative “~10×” copy in the plan warning over fake absolute durations.
- Hero timer shows step-local remaining; whole-job minutes only appear in the note once
  the estimate is measured (`eta_estimated === false`).

## Related

- [01 — App specification](01-app.md) — progress UI surface area.
- [05 — Job queue and concurrency](05-job-queue.md) — queue/nav consume `job.progress`.
- [08 — Performance](08-performance.md) — why guitar dominates wall-clock.
- [architecture.md](../architecture.md) — data flow and ~10× timing table.
