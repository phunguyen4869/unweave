# 12 — Settings panel

Status: Backlog

What this covers: a single place to manage what Unweave has installed and stored. Not
implemented; deliberately deferred until it has enough real content to justify a new
screen.

## Why not yet

Each current setting already lives where the user needs it:

- YouTube support: the YouTube tab offers **Install YouTube support** when it is
  missing, so skipping it at first-run setup is never a dead end.
- Projects folder: **Change** under "Save to" (system folder picker) and the Library's
  folder button.
- Update check: the consent prompt, plus the manual **Check for updates**.

A settings screen that only repeats these adds a second route to the same buttons.
Build it when at least two of the sections below exist.

## Sections (when built)

| Section | Content | Depends on |
|---|---|---|
| Components | What is installed (separation engine, FFmpeg, YouTube, GPU) with sizes; install, repair or remove each | [11 — GPU](11-gpu-acceleration.md) for the GPU row |
| Storage | Model cache size and "Clear models"; per-project and total sizes; "Clear exports" per project | [07 — Disk usage](07-disk-usage.md) cleanup UI |
| Projects folder | Current folder, Change, Use default | Nothing new |
| Updates | Turn automatic checks on or off again after "Don't ask again"; Check now | [10 — Updates](10-updates.md) |
| Language | English / Tiếng Việt (today a title-bar toggle) | Nothing new |

## Constraints

- Removing a component must never touch projects (Documents) and must say what it
  frees and what will need downloading again.
- Cleanup follows spec 07: known locations only, never follow symlinks, never delete
  what the user did not create through the app, and confirm before deleting.
- English and Vietnamese strings for everything.

## Related

- [04 — First-run setup](04-first-run-setup.md), [07 — Disk usage](07-disk-usage.md),
  [10 — Updates](10-updates.md), [11 — GPU acceleration](11-gpu-acceleration.md).
