# 15 — In-app error report (copy diagnostics)

Status: Done

What this covers: letting users copy a plain-text diagnostics bundle when
something fails (or anytime from Settings), so they can paste it into chat or a
GitHub issue. No automatic upload.

## Goal

When setup, separation, YouTube import, or export fails, the user can produce a
**reviewable** text report in one click and send it however they already talk to
you (Messenger, Zalo, Discord, GitHub Issues). Unweave stays local-only: the app
never posts the report to a server.

## Non-goals

- No crash telemetry, Sentry, analytics, or silent background upload.
- No in-app form that emails / webhooks / Discord bots on the user's behalf.
- No requirement for a GitHub account to use the primary action (Copy).
- No attachment of audio, stems, project folders, or model weights.
- No auto-filled GitHub issue body via long query strings (URL length limits;
  clipboard remains the source of truth).

## Why copy-only

Landing and README already point at GitHub Issues. Many Unweave users report
problems over chat in Vietnamese and may not have (or want) a GitHub account.
Copying text matches both channels, needs no new backend, and keeps the
"no telemetry / no accounts" promise in [spec 01](01-app.md).

## Entry points

| Where | When shown | Primary action | Secondary |
|---|---|---|---|
| Setup progress / failed setup | Setup job `failed` (and optionally after a hard error toast for setup) | **Copy error report** | Open GitHub Issues · Facebook |
| Separation / YouTube / export progress | Job `failed` | **Copy error report** | Open GitHub Issues · Facebook |
| Settings → About | Always | **Copy diagnostics** (same payload shape; last error optional / empty) | Open GitHub Issues · Facebook |

Do not add a persistent nav item or a third toast channel. Prefer a button on
the existing failed progress panel (spec 09) and one control under About
(spec 12).

## Report contents

Plain text, UTF-8, English field labels (easier for cross-language paste),
wrapped in a fenced block so chat apps keep newlines:

```text
=== Unweave diagnostics ===
App version: …
Platform: windows | linux | darwin
Arch: …
Python: …
App clock (UTC): …
Setup: runtime=… ffmpeg=… separation=… youtube=…
Last job: kind=… status=… error=…
--- recent log (last N lines) ---
…
=== end ===
```

Rules:

- **Include:** app version (`/api/state` → `version`), `sys.platform`, machine
  arch, Python version used by the UI process, UTC timestamp from the app,
  setup stage booleans from `setup.stages`, last relevant job `kind` / `status`
  / error message, and the tail of that job's log (cap **~80 lines** or
  **~32 KiB**, whichever is smaller).
- **Exclude:** audio files, paths under the projects folder by default, full
  environment dumps, tokens, cookies.
- If a log line contains an absolute path under the configured projects root,
  replace that prefix with `<projects>/` before copying (keep the relative
  remainder so install bugs stay diagnosable).
- User must be able to **see or trust** that only text was copied; show a short
  success notice (`Copied — paste it in chat or a GitHub issue`).

Optional later (out of scope for v1): a "Include last failed job only" vs
"Full diagnostics" toggle. v1 always builds the full short bundle above.

## Backend

Add a small read-only endpoint, e.g. `GET /api/diagnostics` (session token as
usual), that returns JSON:

```json
{
  "text": "=== Unweave diagnostics ===\n…"
}
```

Building the string server-side keeps one source of truth for redaction and log
tailing (job logs already live on the Library). The UI only fetches, writes to
the clipboard (`navigator.clipboard.writeText`), and shows the notice.

No new persisted settings. No network egress beyond what the user does after
paste (browser / OS).

## GitHub link

Secondary control opens the existing issues entry point in the system browser
(same pattern as update "Open download" in spec 10):

`https://github.com/um1chc5/unweave/issues/new`

Also open the maintainer Facebook page the same way:

`https://www.facebook.com/um1chc5/`

Optional follow-up (not required for Done): an issue template under
`.github/ISSUE_TEMPLATE/` that says "paste the diagnostics block from the app
below". Do not rely on pre-filling the body from the app.

## UX / i18n

- Buttons and notices in `en` / `vi` via `i18n.js` (same as the rest of the UI).
- On clipboard failure (permissions / older webview), fall back to selecting the
  text in a small read-only dialog with **Select all** guidance — still no upload.
- Feature remains usable during required first-run setup (SSL / download failures
  are a primary motivation).

## Constraints

- Do not weaken [spec 01](01-app.md) non-goals (no telemetry / accounts).
- Do not send diagnostics on job failure automatically.
- Do not change setup download URLs or SSL verification as part of this spec
  (separate work if we add mirrors / fallbacks).
- Keep the React rewrite ([spec 14](14-react-typescript-frontend.md)) in mind:
  implement against the current vanilla UI; the diagnostics endpoint and copy
  UX should port cleanly.

## Implementation checklist

- [x] `GET /api/diagnostics` builds the redacted text bundle.
- [x] Copy control on failed setup / job progress UI.
- [x] Copy control on Settings → About.
- [x] Secondary “Open GitHub Issues” link (system browser).
- [x] en / vi strings + clipboard failure fallback.
- [x] Tests for redaction (projects path prefix) and size cap.
- [ ] Manual: fail setup (e.g. bad network), copy, paste into an editor; confirm
      no project audio paths and no token.

## Related

- [01 — App specification](01-app.md) — no telemetry.
- [04 — First-run setup](04-first-run-setup.md) — setup failures.
- [09 — Job progress](09-job-progress.md) — failed progress panel.
- [10 — Updates](10-updates.md) — open URL in system browser pattern.
- [12 — Settings panel](12-settings-panel.md) — About tab.
