# 14 — React + TypeScript frontend

Status: Todo

What this covers: replacing the vanilla ES-module web UI (`app/unweave/web/js`, ~4.7k lines) with a typed React application, the build and packaging changes that implies, and the module-by-module migration order.

**Related:** [01 — App specification](01-app.md), [02 — Pre-separation trim](02-pre-separation-trim.md), [09 — Job progress](09-job-progress.md), [12 — Settings panel](12-settings-panel.md), [Architecture](../architecture.md)

### Implementation status

- [ ] Phase 0 — toolchain, build output, packaging, dev proxy
- [ ] Phase 1 — types, API client, i18n, stores (no UI change)
- [ ] Phase 2 — app shell and chrome
- [ ] Phase 3 — New view
- [ ] Phase 4 — Library + Song views and the audio engine
- [ ] Phase 5 — Setup, Settings, Queue, Progress, Plan
- [ ] Phase 6 — delete legacy, CSS co-location, docs

---

## 1. Problem

The frontend works, but it has hit the ceiling of what hand-written DOM code can carry.

| Symptom | Where | Cost |
|---|---|---|
| One mutable global singleton holds 40+ unrelated fields (server state, view, dialog flags, editor instances, buffers) | [store.js](../../app/unweave/web/js/core/store.js) | Any field can be written from any module; no field is typed; nothing says which writes need a re-render. |
| `render()` re-renders *every* view on every poll tick (250 ms while a job runs) | [navigation.js:44](../../app/unweave/web/js/chrome/navigation.js) | Full DOM rewrites for unchanged views; per-view render functions must each defend themselves with "am I visible?" checks. |
| `nav` is an empty object late-bound at startup to break a circular import | [store.js:19](../../app/unweave/web/js/core/store.js), [navigation.js:117](../../app/unweave/web/js/chrome/navigation.js) | The module graph is already cyclic; the workaround is invisible to tooling and crashes only at runtime. |
| 435 `document.getElementById` lookups against 244 ids declared in a 641-line `index.html` | [index.html](../../app/unweave/web/index.html) | Markup and behavior live in different files with a string contract; renaming an id fails silently. |
| 504 i18n keys applied by walking 198 `data-i18n` attributes, 8 of which carry HTML via `innerHTML` | [i18n.js](../../app/unweave/web/js/core/i18n.js) | Keys are untyped strings; interpolation args are unchecked; HTML strings need `innerHTML`, which fights the CSP posture. |
| Server payloads (`/api/state`, jobs, projects, plans) are untyped | [core.js](../../app/unweave/web/js/core/core.js) | `job.guitar_split`, `job.stems`, `job.position` are discovered by reading Python. Shape drift is a runtime bug, never a build error. |

This spec **reverses one goal from [spec 01](01-app.md)**: "Keep the browser-based UI independent of a frontend framework." That constraint bought a zero-build frontend; it now costs more than it saves. Everything else in spec 01 (local-only processing, no telemetry, no accounts, loopback HTTP + token) is unchanged by this work.

## 2. Decision

Rewrite the frontend as a **React 19 + TypeScript (strict) application built by Vite**, served as static files by the existing Python server. The Python API, the audio pipeline, and the visual design do not change. The rewrite is a port, not a redesign: any visual or behavioral change found during migration is a bug unless this spec says otherwise.

### Goals

- Every server payload, i18n key, and component prop is typed; `tsc --noEmit` is a release gate.
- Rendering is derived from state, not from an imperative `render()` broadcast — a job-progress tick updates the progress bar and nothing else.
- Markup lives next to the behavior that owns it; no id-string contract between HTML and JS.
- The audio engine (`StemPlayer`, trim/split editors, SoundTouch worklet) stays framework-free and is wrapped for React, not rewritten.
- `pip install` and the NSIS installer still work on a machine with **no Node.js**.

### Non-goals

- No change to Python routes, payload shapes, the job queue, or the pipeline. If a payload is awkward to type, this spec types it as-is and files a follow-up.
- No visual redesign, no component library, no Tailwind. The six CSS files move but their rules do not.
- No router library, no SSR, no code-splitting beyond Vite defaults. Four views and a handful of dialogs do not need a router.
- No new runtime dependency on a CDN. The Google Fonts links stay exactly as they are today (already allowed by the CSP).

## 3. Stack

| Concern | Choice | Why this and not the alternative |
|---|---|---|
| Build | Vite 7 | Fastest path from ES modules to a bundle; its `publicDir` keeps the AudioWorklet files unbundled (required — see §6). |
| Language | TypeScript 5, `strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes` | The whole point. Loose mode would preserve today's failure mode with extra ceremony. |
| UI | React 19 | Hooks + `useSyncExternalStore` is what the imperative audio engine needs for a clean bridge. |
| Server state | TanStack Query | `/api/state` is a poll with a variable interval (250 ms busy / 2.5 s idle) — `refetchInterval` as a function is exactly this, and it replaces the hand-rolled `poll()` loop plus the `loading`/`controller` fields in the store. |
| UI state | Zustand, split into small typed slices | Replaces the global `store` object. Slices: `view`, `newSeparation`, `song`, `settings`, `dialogs`. No slice may hold a DOM node or an editor instance. |
| i18n | Hand-rolled typed `t()` (ported, not replaced) | 504 keys in one `Record<MessageKey, {en, vi}>` is fine; a library would add weight for no gain. HTML-bearing keys become components (§7). |
| Styling | Existing global CSS, imported from `main.tsx` | Keeping the CSS byte-identical through Phase 5 makes visual regressions obvious. CSS co-location is Phase 6 and optional. |
| Tests | Vitest + React Testing Library | `plan-model.js` is already pure and has a Python-side counterpart in `tests/test_plan.py`; it should be the first thing under test. |

## 4. Layout, build, and packaging

```text
frontend/                      # new: source, not shipped
  index.html                   # keeps <meta name="unweave-token" content="__SESSION_TOKEN__">
  package.json  tsconfig.json  vite.config.ts
  public/                      # copied verbatim to the build output
    tempo-worklet.js
    vendor/soundtouch/
  src/
    main.tsx  App.tsx
    api/      i18n/  state/  audio/  components/  views/  features/  styles/
app/unweave/web/               # build output, committed (see below)
  index.html  assets/*.js  assets/*.css  tempo-worklet.js  vendor/...
```

The Python server keeps `STATIC = unweave/web` ([server.py:18](../../app/unweave/webui/server.py)) and its `__SESSION_TOKEN__` substitution ([server.py:88](../../app/unweave/webui/server.py)) — both work unchanged against a Vite build, because Vite preserves unknown `<meta>` tags in `index.html`.

**The build output is committed to the repo.** A clean `pip install .` or an NSIS build must produce a working app on a machine without Node; the alternative (building in CI only) breaks `pip install -e .` from a fresh checkout and breaks the installer. The tradeoff is a noisy diff per frontend change; mitigate with a CI job that rebuilds and fails if `app/unweave/web` differs from the committed output.

Changes needed outside `frontend/`:

- `app/pyproject.toml` — `package-data` already globs `web/**/*`; confirm `assets/` is picked up.
- `tests/test_package_layout.py:34` — asserts `js/app.js`, `js/audio/trim.js`, `js/chrome/updates.js`, `js/views/settings.js`, `css/base.css` exist. Replace with assertions on `index.html`, `tempo-worklet.js`, `vendor/soundtouch/processor.js`, and "at least one `assets/*.js` and one `assets/*.css`".
- `installer/Unweave.nsis` — copies the app tree recursively; no change expected, but verify the `assets/` subdirectory lands.
- `.gitignore` — ignore `frontend/node_modules`, `frontend/dist`; do **not** ignore `app/unweave/web`.
- `docs/architecture.md` §"Frontend (`web/`)" and spec 01's architecture table need rewriting in Phase 6.

### CSP and the dev server

Production CSP is `script-src 'self'` with no `unsafe-eval` ([server.py:35](../../app/unweave/webui/server.py)). Therefore: `build.target: 'es2022'`, no eval-based sourcemaps in the production build, and no inline `<script>` in `index.html`.

Dev mode needs two things the current setup gets for free:

1. **A token.** `index.html` ships the literal `__SESSION_TOKEN__` and only the Python server rewrites it. Add an opt-in `UNWEAVE_TOKEN` env override in `make_server` (dev only, documented as such), and a Vite `transformIndexHtml` dev plugin that injects the same value from `frontend/.env.local`.
2. **A same-origin API.** The server rejects any request whose `Host`/`Origin` is not its own ([server.py:66](../../app/unweave/webui/server.py)). Configure the Vite proxy for `/api` and `/css`-era static paths with `changeOrigin: true` **and** an explicit `Origin: http://127.0.0.1:8765` header rewrite.

## 5. Module map

| Today | Becomes | Note |
|---|---|---|
| `core/store.js` | `src/state/*.ts` (Zustand slices) + TanStack Query cache | Server fields → query cache; UI fields → slices; editor instances/buffers → refs inside the owning component. |
| `core/core.js` | `src/api/client.ts`, `src/api/selectors.ts`, `src/lib/format.ts`, `src/components/Notice.tsx` | Four unrelated jobs in one 72-line file: fetch, derived state, formatting, toast. Split them. |
| `core/constants.js` | `src/constants.ts` | Tuple-of-tuples (`['vocals', 'stem.vocals', '#ff8a3d']`) → `readonly` object arrays with named fields and `as const`. |
| `core/i18n.js` | `src/i18n/strings.ts`, `src/i18n/t.ts`, `src/i18n/LangProvider.tsx` | §7. |
| `chrome/navigation.js` | `src/App.tsx` + `src/state/view.ts` | `show()`/`selectProject()` become state transitions; `render()` disappears; the `nav` late-bind hack disappears with it. |
| `chrome/{theme,lang-toggle,window,credits,updates,linux-audio}.js` | `src/components/chrome/*.tsx` | `window.ts` keeps its pointer-math as a plain hook (`useWindowDrag`) — it deliberately avoids the pywebview JS bridge; preserve that comment. |
| `views/{new,library,song,setup,settings}.js` | `src/views/<Name>/` (one dir, one entry component, child components under it) | `settings.js` (406 lines, 5 tabs) splits per tab. |
| `features/plan-model.js` | `src/features/plan/model.ts` | Already pure. Port first, type it, unit-test it against `tests/test_plan.py` cases. |
| `features/plan.js` | `src/features/plan/*.tsx` | 555 lines of hand-built SVG + a `M` metrics object. Keep `M` as a typed layout constant; each node/wire becomes a small SVG component. Largest single piece of work. |
| `features/{progress,queue,dialogs,folders,picker,lookup,covers}.js` | `src/features/*/` | `dialogs.js` → a `<Dialog>` wrapper over `<dialog>`; `covers.js`' `Map` of blob URLs → a hook with cleanup on unmount (today the URLs leak). |
| `audio/player.js`, `audio/trim.js`, `audio/split.js` | `src/audio/player.ts`, `src/audio/trimEditor.ts`, `src/audio/splitEditor.ts` | Stay as classes. No React imports. |
| `audio/audio.js`, `audio/transport.js` | `src/audio/usePlayer.ts`, `src/features/transport/*.tsx` | The React bridge (§6). |
| `tempo-worklet.js`, `vendor/soundtouch/` | `frontend/public/` (unchanged bytes) | Must not be bundled (§6). |
| `index.html` (641 lines) | JSX inside the components that own it | Only the shell (`<head>`, token meta, `<div id="root">`) stays in `frontend/index.html`. |

## 6. Audio engine

`StemPlayer` owns an `AudioContext`, a scheduled start time, and a generation counter. It must not become React state — one dropped frame of re-render would audibly break scheduling.

- Classes port to TS unchanged in behavior: typed fields, `#private` where the field is internal, `onError` replaced by a small typed listener set.
- `player.ensureContext()` stays lazy and user-gesture-driven.
- `audioWorklet.addModule('/tempo-worklet.js')` ([player.js:142](../../app/unweave/web/js/audio/player.js)) needs a **real URL at runtime**, and `tempo-worklet.js` itself statically imports `./vendor/soundtouch/processor.js`. Both therefore live in `frontend/public/` and are served at their current paths. Do not let Vite bundle or hash them. A build-time check should assert `web/tempo-worklet.js` exists after `vite build`.
- React reads the player through `useSyncExternalStore` over a change-notifier the player already effectively has (`generation`), plus one `requestAnimationFrame` loop in the transport component for the playhead — replacing the global `animate()` loop, and stopping when nothing is playing.
- One `PlayerProvider` context owns the single player instance for the app lifetime. `clearAudio()` becomes the provider's cleanup for a project change.

## 7. Typing the seams

**API.** `src/api/types.ts` hand-mirrors the Python payloads (`ServerState`, `Project`, `Job`, `SetupState`, `StorageReport`, `CleanupReport`, `UpdateStatus`, `ExportRequest`, `PlanRequest`). `Job` is a **discriminated union on** `kind` (`'separation' | 'youtube' | 'setup' | 'export'`) — the current code tests `job.kind !== 'youtube'` in four places and reads `job.stems`/`job.formats` that only exist on some kinds. `status` is a union (`'queued' | 'running' | 'cancelling' | 'succeeded' | 'failed'`); switches over it must be exhaustive via a `never` default.

`src/api/client.ts` exposes one typed function per route, grouped by file to mirror `webui/routes/`: `system.ts` (state, startup, folders, library, import, importYoutube, cancel, setup, storage, cleanup, updates), `projects.ts` (metadata, cover, separate, splitGuitar, export, reveal, delete, clearExports, audio, original), `meta.ts` (search, prepare, cover). The token is read once from the meta tag and attached by a single `request()` helper; the error shape (`{error}` → thrown `Error`) is preserved.

Hand-written types are a deliberate choice: the Python side has no schema to generate from. Add a Python test that asserts the key set of `/api/state` matches a checked-in fixture, so drift fails a test instead of the UI.

**i18n.** `STRINGS` is `Record<string, {en: string; vi: string}>` declared `as const`; `export type MessageKey = keyof typeof STRINGS`. `t()` takes `MessageKey` and a typed params object, so `t('nav.jobPillText', {what, pct})` is checked and a renamed key is a build error. The eight HTML-bearing keys (`credit.builtOn` etc.) become small components that compose `<strong>`/`<u>` around plain-text sub-keys — no `dangerouslySetInnerHTML` anywhere in the codebase, enforced by an ESLint rule.

## 8. Clean-code rules (enforced, not advisory)

1. `strict` TypeScript. No `any`, no non-null `!`, no type assertions outside `src/api/client.ts` parse boundaries. ESLint `@typescript-eslint` strict + `react-hooks`.
2. No module-level mutable state outside a Zustand store or a class instance owned by a provider.
3. DOM access only through refs, and only inside the component that renders the node. No `getElementById` in `src/`, enforced by `no-restricted-globals`/`no-restricted-syntax`.
4. One component per file, named export, file named after the component. Components over ~150 lines get split.
5. Props are explicit `interface`s. No prop spreading except on native element wrappers.
6. Derived values are selectors (`src/api/selectors.ts`), not duplicated logic — `activeJob`, `jobRunning`, `projectJob`, `queueBusy` already exist and must have exactly one implementation each.
7. Comments explain *why*, matching the existing codebase's density and tone. Several current comments record real bugs (the `render()` setup-gate comment in `navigation.js:45`, the "chunked requests" guard, the 250 ms poll rationale) — **those comments migrate with their code**; losing them re-opens the bugs.
8. No new dependency without a line in this spec.

## 9. Migration order

The views share one `index.html`, one global `render()`, and one store; they cannot be migrated independently in-place. So: one long-lived `frontend/` branch, landed as reviewable phase PRs into that branch, with a single cutover commit at the end. Legacy `web/js` stays untouched and shippable until Phase 6.

| Phase | Scope | Gate |
|---|---|---|
| 0 | Vite + TS + ESLint + Vitest; `public/` worklets; dev proxy and `UNWEAVE_TOKEN`; build writes to `app/unweave/web`; "hello" page loads in the pywebview window | App window opens on the built bundle; `/api/state` reachable in dev through the proxy. |
| 1 | `api/types.ts`, `api/client.ts`, selectors, `constants.ts`, i18n, store slices. No UI. | `tsc --noEmit` clean; Vitest covers selectors, formatters, and the full `plan-model` port against `tests/test_plan.py` cases. |
| 2 | Shell: titlebar, resize edges, appbar/tabs, job pill, notice, three banners (setup, update, linux-audio); poll via TanStack Query | Window chrome, theme and language toggles, and the poll-driven job pill behave as today. |
| 3 | New view: source segmented control, dropzone, YouTube pane, metadata fields + lookup, stem grid, trim editor, output folder picker | Import a file and a YouTube link; trim; start a separation; `continuePending()` resume path works. |
| 4 | Library + Song: project cards, covers, song header, stem tracks, mixer, transport, speed, split dialog, song trim | Full playback parity including original-vs-stems A/B, offset-aware section playback, and speed via the worklet. |
| 5 | Setup, Settings (5 tabs), Queue dialog, Progress dialog, advanced Plan diagram | First-run setup gating; every settings tab; queue with 2+ jobs; plan diagram matches current SVG output. |
| 6 | Delete `web/js` + `web/css` sources from the tree; update `tests/test_package_layout.py`, `docs/architecture.md`, spec 01, `docs/tech-stack.md`; optional CSS co-location | Fresh-clone `pip install .` works with no Node; NSIS installer build tested on Windows; macOS and Linux launch tested. |

Phases 2–5 each end with a manual parity pass against the 1.5.x build running side by side.

## 10. Risks

| Risk | Mitigation |
|---|---|
| Audio scheduling regressions are the hardest class of bug here and the least visible in review | Phase 4 ships with a written manual checklist (play, seek, restart, mute/solo, speed, section-only playback, project switch mid-play) run on all three platforms. |
| The plan diagram (555 lines of bespoke SVG layout) is easy to get subtly wrong | Port `plan-model` first with tests; snapshot-test the rendered SVG geometry against the current output before deleting the old code. |
| Committed build output invites merge conflicts and "forgot to rebuild" | CI rebuild-and-diff check; the build is deterministic (pinned Vite, no timestamps). |
| CSP or worklet path breaks only in the packaged app, not in dev | Phase 0 explicitly verifies the *built* bundle inside pywebview, not just the dev server. |
| Scope creep into a redesign | Visual diffs are regressions by default; any intentional change needs its own spec entry. |

## 11. Acceptance

- `tsc --noEmit`, ESLint, and Vitest pass; no `any`, no `dangerouslySetInnerHTML`, no `getElementById` in `src/`.
- A fresh clone with no Node installed can `pip install .` and run the app.
- All four views, all five settings tabs, both languages, both themes, and the full audio surface behave as 1.5.x — verified by the phase checklists.
- `app/unweave/web/js` and `app/unweave/web/css` no longer exist; `docs/architecture.md`, spec 01, and `docs/tech-stack.md` describe the React frontend.
- No Python route, payload, or pipeline file changed, except the dev-only `UNWEAVE_TOKEN` override and the `/api/state` fixture test.
