# 06 — Close behavior and interrupted jobs

Status: Done

What this covers: what happens when the window is closed while a job runs, why the
result is currently lost, and the planned warning + cleanup. Includes an explicit
decision *not* to implement resume.

## Current behavior (bug)

Closing the window **silently destroys the running job** and leaves debris.

1. **Nothing cancels or waits on close.** There is no `on_closing` / `on_closed`
   handler anywhere. `webview.start()` returns, `main()` falls off the end, and the
   process exits. Both the server thread and the job worker thread are
   `daemon=True`, so they are killed immediately.
2. **The child survives briefly, then freezes.** The job runs as
   `subprocess.Popen(..., start_new_session=True)`, so it is in its own process group
   and survives the parent's death. But the parent reads its output via
   `for line in process.stdout`. When the window closes that reader dies; once the
   pipe buffer fills (~64 KB) the child blocks forever on `write()`.
3. **The result is discarded even if it finished.** Stems are written to a temporary
   directory and only promoted to `stems/` by code that runs *after* `process.wait()`,
   inside the already-dead worker thread.

**Reproduced** by mirroring the exact shape (daemon worker thread,
`start_new_session=True`, stdout to a pipe):

```
--- status right after parent exit ---  alive at step 19
--- is the child still alive? ---      CHILD ALIVE
--- status 5s later ---                alive at step 19   <- frozen on the write
```

The child freezes at the pipe, exactly as predicted.

**Job state is in-memory only** — `self.job` is never persisted to disk. On restart
there is no record the job existed; it vanishes without any message.

### Observable consequence

An interrupted run leaves an orphaned staging directory inside the project:

```
~/Music/Unweave/Landscape (...)/.separation-mq5d5qc3/
```

Found on a real machine (Oct 26), containing an empty `stems/`. Note the project's
real `stems/` directory is timestamped 16 minutes later, so the run was repeated
afterwards. These directories are **never cleaned up**.

## Decision: warn on close — do not implement resume

**Chosen: warn the user and cancel cleanly.** Resume was considered and rejected.

Why not resume:

- `apply_model` **does** process in segments (`segment`, `offset`, `TensorChunk`,
  chunking with overlaps), so partial-work machinery exists — but it is internal to
  the model call and exposes no checkpoint.
- Implementing resume means persisting intermediate stem tensors, tracking segment
  offsets, and restoring them — a new feature *inside a third-party library's
  inference loop*, not something the app can bolt on.
- **It barely helps the common case.** Closing 10 minutes into a 12-minute run loses
  10 minutes; resuming saves ~2. The real fix is preventing the loss, not recovering
  it.

## Planned change — implemented (Phase 1)

In priority order, as spec'd:

1. **Warn before closing while a job runs** — the close button (`$('win-close')`) calls `/api/window/close`; if a job is running and no `confirm` flag is sent, the backend returns `{"confirm": true, "message": "..."}`. The frontend shows the `close-confirm-dialog` and only re-sends close with `{confirm: true}` after the user confirms. Implemented in `web/js/chrome/window.js` and `webui/library.py` `window_action("close")`
(route: `routes/window.py`).

2. **Cancel cleanly on close** — confirmed close calls `library.cancel()` (`JobQueueMixin` in
`webui/queue.py`), cancels all queued jobs, clears the queue, then closes the window.
Every child is started and stopped through `unweave/processes.py` (`popen()` / `stop()`): on POSIX the whole process group is signalled (`SIGTERM`, then `SIGKILL` after 5 s); on Windows each child runs in a Job Object marked kill-on-close, so cancel ends the CLI *and* anything it started (FFmpeg, yt-dlp's FFmpeg), and the tree also dies if the app itself crashes or is ended from Task Manager. Before this, Windows `terminate()` stopped only the direct child; verified on Windows 11 that the old path left a grandchild running and the new one leaves none, for both cancel and a hard-killed host.

3. **Sweep stale staging directories on startup** — `Library.sweep_stale_staging()` is a
   caller of `unweave/cleanup.py`: it removes known interrupted-job and model-download
   leftovers older than 24 h under the projects root, each project folder, and the model
   cache (never system temp — large temp leftovers go through the startup dialog in
   [13 — Leftover clean-up](13-startup-cleanup.md)). Never follows symlinks/junctions.
   Called at end of `Library.__init__`.

4. **Persist minimal job state** — not implemented (deferred, see remaining work).

## Remaining work

- [ ] Optional, deferred: persist minimal job state (id, project, status, started) so an interrupted job can be reported on next launch ("Your last split was interrupted"). The startup staging sweep already handles the data side; do this only if users ask.
- [x] Decided: queued-but-not-started jobs are **cancelled** on close. Retaining them would need queue persistence for an edge case; queued jobs cost nothing to re-add.
- [x] No orphaned child survives a close or cancel on Windows: Job Object kill-on-close in `processes.py` (see item 2).

## Constraints

- Do not remove the staging directories on *every* exit; only sweep ones that are
  stale, so a crash during a legitimate run is still diagnosable.
- The sweep must be conservative: match known prefixes only, skip symlinks, and never
  delete anything outside the projects root.
- Keep the existing `cancel()` semantics; it is the only reliable way to kill the
  child process group.
- Start every long-lived child with `processes.popen()` and stop it with
  `processes.stop()`, never bare `subprocess.Popen` / `terminate()`, or Windows loses
  the tree kill.

## Related

- [05 — Job queue](05-job-queue.md) — what happens to queued jobs on close.
- [01 — App specification](01-app.md) — job lifecycle and staging directories.
- [07 — Disk usage and cache](07-disk-usage.md) — the full inventory of what the app
  writes.
