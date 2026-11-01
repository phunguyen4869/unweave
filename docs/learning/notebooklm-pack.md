# NotebookLM learning pack — Unweave

Use this pack with [NotebookLM](https://notebooklm.google.com/) (Gemini) to learn the
technical side of Unweave quickly. Prefer **public GitHub links** (no file upload).
Paste the starter prompt, then work through the question sets.

## 1. Add sources via links (preferred)

Create a notebook named **Unweave — Technical** → **Add sources** → **Websites** /
paste URLs. NotebookLM scrapes **that page only** (not the whole repo), so add one
URL per doc. Use `raw.githubusercontent.com` so it gets clean Markdown text.

Repo: `https://github.com/um1chc5/unweave` (branch `main`).

### Limits to know

- Public URLs only; private / unpushed local edits will not appear.
- Snapshot at import time — re-add a URL after docs change if you need freshness.
- Cap is about **50 sources** per notebook.
- A GitHub *folder* or repo home page is not enough; list **file** URLs.

### Must-have (paste as one batch)

```
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/overview.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/architecture.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/tech-stack.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/README.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/01-app.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/learning/study-guide.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/learning/notebooklm-pack.md
```

| Doc | Why |
|---|---|
| `docs/overview.md` | Product + package map |
| `docs/architecture.md` | Data flow, design rules, modules, models |
| `docs/tech-stack.md` | Stack choices and rejected alternatives |
| `docs/specs/README.md` | Spec board + read order |
| `docs/specs/01-app.md` | Full app behavior contract |
| `docs/learning/study-guide.md` | Condensed brief |
| `docs/learning/notebooklm-pack.md` | This pack (prompts live here too) |

### Strongly recommended (jobs / progress / packaging)

```
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/05-job-queue.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/09-job-progress.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/08-performance.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/04-first-run-setup.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/desktop-app.md
```

### Optional deep dives

```
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/02-pre-separation-trim.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/03-output-formats.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/06-close-behavior.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/07-disk-usage.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/11-gpu-acceleration.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/12-settings-panel.md
https://raw.githubusercontent.com/um1chc5/unweave/main/docs/specs/13-startup-cleanup.md
https://raw.githubusercontent.com/um1chc5/unweave/main/README.md
```

### Fallback: upload files

If a doc is only local (not pushed yet), or a raw URL fails, drag-and-drop the `.md`
from disk instead. Prefer docs over dumping the whole code tree; ask NotebookLM which
modules matter, then open those in the repo.

**Note:** `docs/learning/*` must be on `main` before the learning URLs work. Until you
push this pack, upload `study-guide.md` / `notebooklm-pack.md` locally, or use the
other raw links that already exist on GitHub.

## 2. Starter prompt (paste first)

Copy everything inside the fence into the NotebookLM chat:

```
You are my technical tutor for Unweave, a local desktop stem-separation app
(Python package `unweave` + vanilla JS UI + stdlib HTTP server + pywebview).

Rules:
- Ground every answer in the uploaded sources. Cite the source file name.
- Prefer architecture and design rules over trivia.
- When explaining a flow, name the layers: UI → HTTP server → job queue →
  worker process (`python -m unweave`) → engines (FFmpeg / PyTorch / ONNX) → disk.
- Call out non-obvious invariants (atomic publish, one multi-stem model,
  scratch inside staging, process-tree kill, polling vs stderr streaming).
- If sources conflict or are silent, say so explicitly.
- Keep answers tight: short overview, then bullets, then a “check your understanding”
  question for me.

Start by producing:
1) A 10-bullet “Unweave in one screen” summary.
2) A layer diagram in text (UI / server / queue / worker / engines / FS).
3) A recommended 5-day study path using only the uploaded docs.
```

## 3. Follow-up prompt sets

Use these after the starter. One set per study session.

### Day A — Big picture

```
Teach me the product and package layout from overview.md and architecture.md.
Explain: what stays local, what touches the network, and why the package is
still named unweave / cache .sound-razor. End with a quiz of 5 questions
(answers after I reply).
```

### Day B — Separation pipeline

```
Walk me through one separation end-to-end using architecture.md.
For each of the 7 stages: inputs, key functions, outputs on disk, failure mode.
Emphasize select_model(), atomic publish, and why guitar split is ~10× cost.
```

### Day C — Jobs, progress, UI refresh

```
Using specs 05 and 09 plus architecture.md, explain:
1) How the queue supervises the worker (stream vs poll).
2) How the UI gets status (GET /api/state).
3) progress vs step_progress vs ETA.
Compare polling vs WebSocket for this local app and argue which fits better
given the sources.
```

### Day D — Desktop packaging & first run

```
Using tech-stack.md, desktop-app.md, and spec 04: explain why NSIS + embedded
Python + pywebview + first-run download was chosen over Electron/Tauri/PyInstaller.
Then outline the first-run stages and what is gated until setup succeeds.
```

### Day E — Design rules drill

```
Quiz me on the Design rules section of architecture.md.
Ask one rule at a time. I answer; you correct with the source wording.
After 10 rules, summarize which bugs each rule prevents.
```

## 4. Flashcard / Audio Overview prompts

NotebookLM also has Study Guide / FAQ / Audio Overview. After sources are uploaded:

**Study Guide custom focus**

```
Focus on: separation data flow, job queue, progress fields, model selection,
atomic publish, desktop packaging tradeoffs. Ignore marketing language.
```

**FAQ custom focus**

```
Generate FAQs a new contributor would ask before their first PR touching
audio/pipeline.py or webui/library.py.
```

**Audio Overview nudge (in chat, then generate)**

```
Prepare talking points for an Audio Overview aimed at a mid-level engineer
new to this repo: 8–10 minutes, technical, no hype.
```

## 5. Quick map of key modules (cheat sheet)

| Concern | Start here |
|---|---|
| Separation orchestration | `app/unweave/audio/pipeline.py` |
| Guitar lead/rhythm | `app/unweave/audio/guitar_split.py` |
| Model download / SHA | `app/unweave/audio/model_cache.py` |
| Export re-encode | `app/unweave/audio/exports.py` |
| HTTP API | `app/unweave/webui/server.py` |
| Job queue + progress parse | `app/unweave/webui/library.py` |
| Project on-disk format | `app/unweave/projects/store.py` |
| First-run install | `app/unweave/setup_env.py` |
| Process tree kill | `app/unweave/processes.py` |
| UI poll loop | `app/unweave/web/js/app.js` |
| Progress UI | `app/unweave/web/js/features/progress.js` |

## 6. Success check

You “get” the project when you can answer without notes:

1. Why the UI never imports torch.
2. Why multi-stem plans always use `htdemucs_6s`.
3. How a cancelled job avoids half-written stems.
4. How progress reaches the UI (stderr stream → queue memory → HTTP poll).
5. What runs in-process vs subprocess.
