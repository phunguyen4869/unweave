# 08 — Performance and hidden optimizations

Status: Done (Items 1–2)

What this covers: "background" maintenance and performance work that is invisible in
the UI but affects how fast jobs run and how much the app writes to disk. Complements
[07 — Disk usage and cache](07-disk-usage.md), which covers *space*; this covers
*time and churn*.

Ordered by measured impact. Each item notes whether it is verified or a hypothesis.

## 1. Hardcoded 4 threads in guitar split (verified, highest impact)

[`audio/guitar_split.py:65`](../../app/unweave/audio/guitar_split.py) calls
`torch.set_num_threads(4)` unconditionally, so a 12-core machine uses a third of its
cores. Measured on this 12-core box (large matmul, proxy for the RoFormer
compute-bound path):

| Threads | Time | Speedup |
|---:|---:|---:|
| 1 | 137.4 ms | 1.00x |
| 2 | 71.3 ms | 1.93x |
| 4 | 37.3 ms | 3.69x |
| 8 | 36.4 ms | 3.78x |
| 12 | 25.2 ms | **5.45x** |

Going from 4 → 12 threads is a further **~1.5x** on top of the 3.7x already gained.
Note 4 → 8 is nearly flat (37.3 → 36.4 ms), so the win is specifically at the top end;
the right answer is to size to `os.cpu_count()` rather than pick another constant.

Also relevant: Demucs/MDX inference in `audio_separator` never sets thread counts at
all, so it falls back to PyTorch's default (= all cores). That is fine on a dedicated
machine but means a separation job can starve the UI thread.

**Done:** threads set to `max(1, os.cpu_count() - 1)` via `cpu_threads()` in `tools.py`,
overridable with `UNWEAVE_THREADS` env var. Applied consistently to both the RoFormer
path (`guitar_split.py`) and the Demucs/MDX path (`pipeline.py` calls
`torch.set_num_threads(cpu_threads())` before creating the separator).

## 2. Redundant stem I/O: every stem is written three times (verified)

A separation job moves each stem through three copies:

1. `audio_separator` writes into `output_dir=str(work)` — the OS temp dir.
2. `shutil.copyfile()` copies each stem into a `.stems-*` staging dir **inside the
   project** (this is deliberate: it keeps the final `replace()` on one filesystem).
3. `replace()` renames the staged file onto the destination.

For a 4-minute song with 6 stems (10.1 MB per stem per minute):

```
stems total: 242 MB
written 3x : 727 MB of I/O   (redundant: 485 MB)
```

Half a gigabyte of avoidable writes per job. The staging step itself is correct — the
comment explains it exists so replacement never falls back to copying over an existing
file that might be a link — but step 1 → 2 is pure duplication.

**Done:** `audio_separator` now writes directly into the project-local staging dir
(`output_dir=str(stage)`), eliminating the temp-dir copy. Staging is created before
inference and cleaned up on failure (via `TemporaryDirectory`). `combine_other()`
still works — it writes to a sibling temp file within staging and replaces onto the
final stem in staging, then everything is atomically `replace()`d onto the destination.

## 3. Small-file churn on Windows (hypothesis)

The jobs above land in `%TEMP%`, the project's `stems/`, and per-job staging dirs
under `Documents`. On Windows, real-time AV (Defender) scans newly written files, and
this app writes many multi-MB WAVs per job — the 727 MB of churn in item 2 is
multiplied by scanning cost. Worth measuring on a real Windows install before acting.

**Possible mitigations:** recommend an exclusion for the models directory, and/or
reduce churn (item 2) so there is less to scan.

## 4. Per-job import cost (measured, low impact)

Each job is a fresh subprocess. Measured with the real venv:

| Import | Time |
|---|---:|
| bare python | 0.01 s |
| `numpy` | 0.07 s |
| `torch` | 1.03 s |
| `torch` + `audio_separator` | 1.09 s |

Only ~1.1 s, paid once per job against minutes of inference — **not worth optimizing**
(a worker-process pool would add complexity for no measurable gain). Documented so
nobody "optimizes" it later.

The 589 MB *resident* cost is the real per-job constraint, covered in
[05 — Job queue](05-job-queue.md).

## 5. State polling is cheap — leave it alone (measured)

`/api/state` calls `list_projects()`, which does a full directory scan and reads
`metadata.json` + `separation.json` per project on **every poll** (1 s while a job
runs, 2.5 s idle — see `app.js`). Measured at **0.7 ms per call for 4 projects** with
a 4.3 KB payload. That is negligible.

It does scale linearly: at ~1,000 projects this is ~175 ms per poll. Only worth
caching (e.g. mtime-keyed) if libraries that large are realistic. Not a current
problem.

## 6. `combine_other()` builds a float32 mix (context)

When folding unselected stems into "Other", `amix` writes **`pcm_f32le`** — double the
size of the final `pcm_s16le`, written to a sibling temp file. Correct (preserves sums
above full scale without clipping) but worth knowing when accounting for job I/O.

## 7. Dev-only: `uv` cache bloat (not shipped)

`~/.cache/uv` is **1.4 GB** on this machine (the app's own model cache is 455 MB, for
comparison). `uv cache clean` reclaims it. Only relevant to maintainers, not users —
noted so it is not mistaken for app bloat.

## Remaining work

- [ ] Benchmark a real guitar split at 4, 8 and `cpu_threads()` threads (and physical
      vs logical core count) to confirm the matmul proxy translates to wall-clock
      savings. Do it with the GPU work below.
- [x] Closed: Defender measurement. Item 2 removed most of the churn it would have
      amplified; reopen only if someone reports slow writes.
- [x] Decided: **no** worker-process pool for imports; measured cost is ~1.1 s.
- [x] The UI server no longer imports torch to detect CUDA (it kept hundreds of MB
      resident in a process that never runs inference); see [05](05-job-queue.md).
- [x] Parallel jobs (CUDA builds only) share the cores: `Library._thread_env()` passes
      `UNWEAVE_THREADS = cpu_threads() // max_concurrent_jobs` to each job's CLI, unless
      the user set `UNWEAVE_THREADS` themselves.
- [ ] GPU path, now [11 — GPU acceleration](11-gpu-acceleration.md): the guitar split is hard-coded to CPU
      (`map_location='cpu'`, no device move), and the Windows PyPI torch is a CPU
      build. Optional CUDA setup step + device selection in `guitar_split.py` +
      VRAM-aware concurrency. Biggest remaining speed-up.

## Constraints

- Keep the `.stems-*` staging step: replacing onto the destination filesystem is what
  prevents a cross-filesystem copy over an existing file that could be a link.
- Leave one core free for the HTTP server and UI; do not set threads to the full core
  count.
- Do not change `validate_outputs()` ordering — it exists to reject symlinked or
  unexpected destinations before anything is written.

## Related

- [07 — Disk usage and cache](07-disk-usage.md) — space, uninstall, and cache.
- [05 — Job queue](05-job-queue.md) — per-job memory cost and the concurrency cap.
- [03 — Output formats](03-output-formats.md) — the export path's FFmpeg work.
