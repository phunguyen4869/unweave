# 12 — Settings panel

Status: Done

What this covers: a single place to manage what Unweave has installed and stored,
plus About. Opened from the gear button in the app bar (next to language / theme).

## Why it exists now

Storage cleanup (spec 07) and a way back into update checks after “Don’t ask again”
(spec 10) finally give the screen enough real content. About lives here too, so one
dialog replaces the old separate About popup. The Separate / Library surfaces keep
their own shortcuts where they already lived.

## UI

One modal `<dialog>` (~880×580, max 92vw / 88vh) with a fixed left sidebar (~200 px)
and a scrolling content pane. Sidebar tabs, in order:

| Tab | Content |
|---|---|
| General | Language (English / Tiếng Việt) and Projects folder (path, Default tag, Change → `openFolder()`, Use default). |
| Components | Runtime, FFmpeg, separation engine, YouTube — installed state and size from `/api/state` `setup.stages`. Install / Repair call `/api/setup/start` for that stage (`repair: true` for Repair). No GPU row (spec 11 stays backlog). Runtime is installer-only. Shared card markup with first-run setup (`web/js/features/components.js`). |
| Storage | Model cache size + Clear models; projects total; per-song sizes with Clear exports (existing confirm dialogs). Duplicate titles also show the folder name. **Leftover files** row (spec 13): last scan summary, Scan again, Clean up, auto switch. `/api/storage` and `/api/cleanup` are fetched only when this tab opens (and after a clear/scan), never from the 1 s render loop. |
| Updates | Switch for automatic checks (`POST /api/updates/prefs` with `check: "auto"` / `"manual"`) and Check now (`checkForUpdatesManual`). |
| About | Version, tagline, credits from `credits.js`, full-credits link, copyright/licence. Replaces the old `#about-dialog`. |

ARIA: `role=tablist` / `tab` / `tabpanel`, `aria-selected`, Up/Down arrows move tabs,
Esc and × close. Last selected tab is remembered for the session. Usable during
required first-run setup (language, folder, About) and while jobs run (destructive
buttons stay disabled). Only component install chips refresh on the poll loop.

Strings are in `web/js/core/i18n.js` for `en` and `vi`. Verified at 1280×900 and the
minimum window 1100×700, dark and light, both languages.

## Repair

`POST /api/setup/start` accepts `repair: true`. For the requested stages,
`run_setup(..., repair=True)` reinstalls even when already present: FFmpeg is
downloaded again; separation and YouTube use pip `--force-reinstall`. Shown as a
normal setup job.

## Backend

- `GET /api/storage` — model cache and per-project byte totals (`Library.storage_info`).
  Snapshot root / cache / project list under `Library.lock`, then size on disk
  **without** the lock so `/api/state` polling stays responsive
  (`SettingsMixin.storage_info()` in `webui/settings.py`). `dir_bytes` skips
  symlinks and Windows junctions.
- `POST /api/storage/clear-models` — clears only the known models cache; refuses while
  jobs run (check under the lock).
- `POST /api/projects/<id>/clear-exports` — removes only that project’s `exports/`;
  never stems or originals (check under the lock).

Cleanup follows spec 07: known locations only, never follow symlinks/junctions,
confirm in the UI before deleting.

## Related

- [04 — First-run setup](04-first-run-setup.md), [07 — Disk usage](07-disk-usage.md),
  [10 — Updates](10-updates.md), [11 — GPU acceleration](11-gpu-acceleration.md),
  [13 — Leftover clean-up](13-startup-cleanup.md).
