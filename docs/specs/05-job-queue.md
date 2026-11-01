# 05 — Job queue and concurrency

Status: Done

What this covers: why only one job runs at a time, what the real limit is, and the
planned change from *rejecting* concurrent requests to *queueing* them (with an
optional, configurable concurrency cap).

## Current behavior

Exactly one job exists at a time. Every entry point opens with the same guard and
**rejects** a second request outright — it is not queued:

```python
if self.running() or self.worker is not None and self.worker.is_alive():
    raise ValueError("Another download or separation is already running.")
```

That guard appears in four places in [`webui/library.py`](../../app/unweave/webui/library.py):
`start()` (separation), `import_youtube()`, `start_setup()`, and `start_export()`.

The limit is a consequence of the data model, not a resource check. `Library` holds
three **scalars** — `self.job`, `self.process`, `self.worker` — plus one shared
`self.logs` deque. `/api/state` returns `"job": job`, a single object, and the
frontend reads `store.state.job` in six places (`progress.js`, `library.js`,
`new.js`, `setup.js`, `song.js`, and the setup view).

There is **no** hardware detection anywhere: no `cpu_count`, no memory probe, no
`Semaphore`, no `Queue`, no `max_workers`, no `concurrent.futures`. The only
threading-adjacent calls are `torch.set_num_threads(4)` inside guitar split (bounding
*one* job's own threads) and `torch.cuda.is_available()` (device selection).

## Why the limit exists (and is defensible)

Each job shells out to a **fresh `unweave` subprocess**, so per-process costs are
paid per job. Measured import cost on a clean interpreter:

| Stage | Cumulative RSS |
|---|---:|
| baseline Python | 10 MB |
| + `numpy` | 26 MB |
| + `torch` (import only) | 501 MB |
| + `audio_separator` import | **589 MB** |

On top of that: `htdemucs_6s` weights (~55 MB) plus activation memory that scales
with audio length — realistically **1.5–2.5 GB resident per job**.

- **RAM is the binding constraint, not CPU.** On a 12-core / 31 GB machine, 3–4 jobs
  fit. On the 8 GB Windows target in the README, **2 is already risky**.
- **CPU argues the same way.** A Demucs run already saturates the cores, so parallel
  jobs split the same throughput — both finish later and both ETAs become wrong.
- **GPU changes the answer.** A 12 GB card can genuinely run 2–3 concurrently, which
  is why the cap should be configurable rather than hardcoded.

## Planned change

Two phases. Phase 1 alone removes most of the friction and keeps the resource profile
identical.

### Phase 1 — Queue (done)

Replace rejection with a FIFO queue that runs **one job at a time**. Implemented on branch `dev/new-specs`:

- `self.job` / `self.process` / `self.worker` replaced by `queue` (pending job records) plus a single `active` record, drained by one worker thread — peak memory and CPU unchanged.
- `/api/state` returns `"jobs": [...]` plus `"active_job"`; a `job` shim field is kept for frontend compatibility.
- Frontend reads `store.state.jobs` / `store.state.active_job` via `jobRunning()`; the job pill shows the queued count.
- Cancelling a pending item removes it from the queue; cancelling the active item uses the existing `cancel()` path (`os.killpg` / `terminate`, then `SIGKILL` after 5 s).
- Per-job logs moved from one shared deque to per-job buffers keyed by job id.
- Requests return immediately with a job id; the HTTP thread never blocks waiting for a queue slot.
- `worker` attribute removed (no longer used); `server.py` joins the drainer thread on shutdown.

Per-job logs are now keyed by job id, so progress lines stay attributable.

## Remaining work

- [x] Phase 2 derived cap: `_derive_max_concurrent_jobs()` gives `1` on a CPU build of torch and `3` on a CUDA build, capped at one job per 3 GB of RAM; `UNWEAVE_MAX_CONCURRENT_JOBS` overrides it. The CUDA check reads torch's files (`setup_env.torch_has_cuda()`) instead of importing torch into the UI process, and RAM is read with `GlobalMemoryStatusEx` on Windows, where `os.sysconf` does not exist.
- [x] Decided: **no** in-app concurrency setting. On CPU the right value is 1; a visible knob mostly lets users slow the app down. The env variable covers power users.
- [x] Decided: queued jobs are cancelled when the window closes (see [06 — Close behavior](06-close-behavior.md)).
- [x] Decided: **no** queue depth limit. Queued jobs cost nothing until they start, and each start re-checks disk space ([07](07-disk-usage.md)).

## Constraints

- Do not raise concurrency without a cap; an uncapped queue with parallel execution
  would exhaust RAM on the 8 GB target machine.
- Keep `cancel()`'s process-group semantics (`os.killpg` on POSIX, `terminate()` on
  Windows) — it is the only thing that reliably kills the child and its workers.
- Do not block the HTTP request thread while waiting for a queue slot; the request
  should return immediately with a job id.

## Related

- [01 — App specification](01-app.md) — job/state model and the progress UI.
- [04 — First-run setup](04-first-run-setup.md) — setup runs as a job too, so it is
  subject to the same queue.
- [06 — Close behavior](06-close-behavior.md) — interaction with queued jobs.
- [09 — Job progress and ETA](09-job-progress.md) — how queue/nav `progress` and detail
  step timers are derived (especially with guitar split).
