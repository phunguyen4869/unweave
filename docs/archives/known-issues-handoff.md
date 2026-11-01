# Known issues — handoff (installer + first-run setup)

Three real bugs found this session, not yet fully fixed/shipped. Written up
for a fresh session (Kilo) to pick up, since the current session is low on
budget.

## 1. Setup screen reads the wrong folder → "Can't read C:\Program
   Files\pyproject.toml"

**Root cause, confirmed:** [`_install_dir()` in setup_env.py](../app/unweave/setup_env.py)
line 36:
```python
def _install_dir() -> Path:
    return Path(__file__).resolve().parents[2]
```
`__file__` is `$INSTDIR\unweave\setup.py`. `.parents[0]` is
`$INSTDIR\unweave`, `.parents[1]` is `$INSTDIR` (correct target),
`.parents[2]` is one level too high — the parent of $INSTDIR, which for a
Program Files install is literally `C:\Program Files`. Off-by-one.

**Fix:** change `parents[2]` to `parents[1]`.

**Also audit:** grep the whole file (and anywhere else `_install_dir()` or
similar `Path(__file__).resolve().parents[N]` patterns appear) for the same
mistake — this exact function is used to locate `pyproject.toml`,
`ffmpeg.exe`/`ffprobe.exe`, and probably other install-relative paths for
the setup/first-run flow. Every one of them needs to resolve to `$INSTDIR`
(where `ui_entrypoint.py` and `unweave/` actually live), not one level
above it.

## 2. `pythonw.exe` shortcut silently does nothing on a real install

Confirmed via live back-and-forth with the user on their actual machine:
- The Start Menu shortcut (target: `runtime\pythonw.exe`) produced **no
  window, no process, no Application event log entry, nothing** when
  clicked.
- The exact same install, launched with `runtime\python.exe` instead
  (visible console) from a terminal the user opened themselves, **worked
  immediately** — app opened.
- From this session's own side, launching the exact same `pythonw.exe` +
  args + working directory via PowerShell's `Start-Process` **did**
  successfully open a window — could not reproduce the failure remotely.
  Confirmed this session's shell runs in the same interactive session
  (Session 1, same as `explorer.exe`) as the user, so it isn't a
  session-isolation difference.

**Root cause: unknown.** Something about `pythonw.exe` specifically (no
console/no stdio) fails on this real install in a way that:
- Doesn't reach the Application event log (so no .NET/Windows Error
  Reporting crash, or it reached WER but the specific event wasn't found
  in a 10-minute-window query — worth re-checking with a wider window and
  `Get-WinEvent -FilterHashtable @{LogName='Application'}` generally, not
  just `*python*`-matching, since pywebview/pythonnet might log under a
  different provider name).
- Doesn't print anything `python.exe`'s console would have shown — so if
  it's a Python-level exception, it's happening at a point that `pythonw`
  swallows (unhandled exception in `pythonw.exe` goes nowhere visible, not
  even a crash dialog, by design).

**Mitigation already applied in code (not yet rebuilt/released):**
[installer/Unweave.nsis](../installer/Unweave.nsis) — changed both
`CreateShortCut` lines (Start Menu is already changed; **the Desktop
shortcut section was NOT yet updated to match — do that too**) from
`runtime\pythonw.exe` to `runtime\python.exe`, trading a visible console
window for "actually opens." This is a pragmatic workaround, not a real
fix — the underlying `pythonw.exe` failure is still unexplained.

**To actually root-cause it** (if worth the time vs. just shipping the
`python.exe` workaround): the user has reproduced this reliably once. The
most useful next step would be asking them to run `pythonw.exe` with
`py_compile`-level tracing, or — simpler — add a very early
`try/except Exception: Path(os.environ['TEMP'], 'sr-crash.log').write_text(traceback.format_exc())`
around the top of [app/ui_entrypoint.py](../app/ui_entrypoint.py)'s `main()`
(or even around the module-level `import webview` / `from unweave.webui import serve`
lines), ship that as a diagnostic build, and have them run the `pythonw.exe`
shortcut once more and check `%TEMP%\sr-crash.log` afterward. That would
finally surface what's actually failing without needing a console.

**Action for this task:**
1. Finish the `python.exe` swap for the Desktop shortcut section too
   (currently only Start Menu was changed).
2. Rebuild (`cd installer && makensis Unweave.nsis`).
3. **Actually test on a real Program Files install** (this session
   couldn't fully verify — no admin rights in that shell). Install for
   real, click the Start Menu icon, confirm a window (with console behind
   it) opens.
4. If budget allows, add the crash-log diagnostic above *before* committing
   to `python.exe` as the permanent answer — `pythonw` with no visible
   console is the better end-user experience, and it's worth knowing why
   it fails before giving up on it. If not, ship the `python.exe` swap as-is
   and leave this doc's root-cause section for later.

## 3. Setup/consent screen doesn't gate the UI the way it's supposed to

User's report: after install, **both tabs (Separate / Library) are visible
and usable immediately** — the one-time setup/consent screen (that's
supposed to ask before downloading FFmpeg/PyTorch/etc., per
[docs/specs/04-first-run-setup.md](specs/04-first-run-setup.md)) isn't actually
gating anything, or isn't showing at all. Needs investigation into
`app/unweave/web/index.html`'s `#view-setup` section and the
`webui/` + `web/js/` logic supposed to route the user there first on a fresh install
(look for `state.setup` and setup-stage constants in `web/js/views/setup.js`
and the navigation modules; these decide which view shows first).

**Also requested (new, not yet built):** the setup screen should visually
distinguish, per component, whether it's **already present** vs **needs
downloading** — icon/color coded (e.g. a checkmark + muted color for
"already have it", a download icon + accent color for "needs
installing"), not just a flat list. This means the setup screen's data
needs a per-item boolean (already-satisfied vs missing) that the backend
already effectively computes (see `runtime_ok()`, the ffmpeg check, etc. in
[`setup_env.py`](../app/unweave/setup_env.py) — bug #1 above is
in that same file) — wire that per-item status through to the setup UI
instead of just a flat requirements list.

## Context for whoever picks this up

Paths updated after the package refactor; the historical bug descriptions below retain their original context.

- Repo: https://github.com/um1chc5/unweave (public)
- Releases so far: v1.0.0 through v1.0.3. v1.0.3 is the last one with a
  working installer *location* but still has bug #1 and #2 above — don't
  point the user back at v1.0.3 as "the fix," it isn't.
- Installer is NSIS ([installer/Unweave.nsis](../installer/Unweave.nsis)),
  installs to Program Files (admin-elevated), has an opt-in desktop-icon
  page. Embedded Python runtime is prebuilt at
  `installer/embedded/runtime/` (gitignored — rebuild steps are in the
  `.nsis` file's header comment).
- The app itself (not the installer) already got a real, verified fix this
  session for a *different* bug: it used to write config/models/output to
  paths relative to its own folder, which broke under Program Files
  (no write access without elevation). That's fixed — config/cache now go
  to `%LocalAppData%\Unweave`, default output to
  `Documents\Unweave`. Don't revert that.
