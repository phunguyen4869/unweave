# 10 — In-app update check

Status: Done

What this covers: asking permission to check for updates, how checks run, how a newer
release is shown, and what is explicitly out of scope (no silent auto-install).

## Goal

Let users learn when a newer Unweave build is available, without surprising network
traffic or auto-replacing the install. Checking GitHub Releases requires consent;
manual “Check for updates” always remains available.

## Consent (first launch)

After the main window is up (and preferably after required first-run setup is complete
or dismissed — not before the app is usable), show a light dialog once:

- Title / body: Unweave can check GitHub for newer versions. No account; only a version
  lookup.
- Actions: **Allow** · **Not now**
- Checkbox: **Don’t ask again** (default unchecked)

| Choice | Persist | Behavior |
|---|---|---|
| Allow | `updates.check = "auto"` | Background check on launch (throttled) |
| Not now, don’t ask again | `updates.check = "manual"` | Never auto-check; About → Check for updates only |
| Not now, ask again | `updates.check = "ask"` + `ask_again_at` (~7 days) | Show the same dialog on a later launch after that time |

Store preference in the app config file next to other UI settings
(`%LOCALAPPDATA%\Unweave\ui.json` or the existing config path), not only `localStorage`,
so it survives clearing site data inside the webview. Changing the projects folder
preserves the `updates` section.

No network call until **Allow** or an explicit manual check.

## Auto check (when allowed)

- Trigger: app start (after UI ready), at most once per **24 hours** (persist
  `updates.last_checked_at`).
- Source of truth: GitHub Releases API for this repo’s latest stable release
  (`/repos/um1chc5/unweave/releases/latest` — ignores drafts and prereleases).
- Compare to the running app version from `/api/state` → `version` (same as About).
- Semver-ish compare for shipped tags (`1.3.1`); do not treat a failed
  network call as “up to date” — stay quiet for auto, show a soft error only
  when the user asked.
- Offline / timeout: fail silently for auto checks; surface a short error for manual.

## When a newer version exists

- Non-blocking banner (“Version X.Y.Z is available — you have A.B.C”).
- Primary action: **Open download** → latest release page.
- Secondary: **Later** / dismiss (remember `dismissed_tag` until a newer tag appears).
- Do **not** download the installer into Program Files, run it, or replace files
  automatically in this phase.

## Manual check

- Entry point: About dialog → **Check for updates**.
- Always allowed regardless of consent mode.
- If already on latest: short “You’re up to date” notice.
- If newer: same non-blocking update banner as auto check.

## Privacy / product constraints

- Unweave remains no-account, no telemetry. The only outbound request for this feature is
  the Releases lookup the user allowed (or triggered manually).
- Do not send machine id, project list, or setup state with the request.
- User-Agent identifies the app name + version for GitHub etiquette.

## Implementation

- Backend: [`app/unweave/updates.py`](../../app/unweave/updates.py) (compare + fetch);
  prefs / check on `Library` in [`webui/library.py`](../../app/unweave/webui/library.py);
  routes `GET /api/updates/status`, `POST /api/updates/prefs`, `POST /api/updates/check`.
- Frontend: [`web/js/updates.js`](../../app/unweave/web/js/updates.js) — consent dialog,
  start-of-session auto check when `auto`, About manual button, update banner.
- Tests: [`tests/test_updates.py`](../../tests/test_updates.py).

## Out of scope (this spec)

- In-place / silent auto-install, delta patches, or a built-in updater service.
- Channel selection (stable vs beta) beyond “ignore prereleases by default”.
- Checking for model or dependency updates (setup / lazy model download stays separate).
- Forcing an update before the user can use the app.

## Checklist

- [x] Consent dialog + don’t-ask-again persistence in app config
- [x] Auto check throttled to ≤1 / 24 h when allowed
- [x] Manual check from About
- [x] Newer-version banner with open-release CTA
- [x] No network before consent / manual action
- [x] Spec board + About copy (en/vi)

## Related

- [04 — First-run setup](04-first-run-setup.md) — show update consent after the app is usable,
  not ahead of required setup.
- [01 — App specification](01-app.md) — About / version surface.
- [desktop-app.md](../desktop-app.md) — how releases are packaged and published.
