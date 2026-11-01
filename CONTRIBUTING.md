# Contributing to Unweave

Thanks for your interest in Unweave. Contributions are welcome via pull requests
from a **fork**. Direct branch creation on this repository is restricted to the
maintainer.

## How to contribute

1. **Open an issue first** for anything non-trivial (new feature, behavior change,
   or larger refactor). Small bug fixes and docs tweaks can go straight to a PR.
2. **Fork** the repository on GitHub.
3. **Clone your fork** and create a branch there:
   ```bash
   git clone https://github.com/<your-username>/unweave.git
   cd unweave
   git checkout -b fix/short-description
   ```
4. Make your changes, then push to **your fork** and open a pull request against
   `um1chc5/unweave` `main`.

Do not open a PR from a branch on the upstream repo — contributors cannot create
branches there. Work on your fork and target `main`.

## Development setup

Requirements: Python 3.11+, [uv](https://github.com/astral-sh/uv) recommended.

```bash
uv venv --python 3.11 .venv

# Windows
uv pip install --python .venv/Scripts/python.exe -e ".[full]"
.\.venv\Scripts\unweave.exe

# Linux / macOS
uv pip install --python .venv/bin/python -e ".[full]"
.venv/bin/unweave
```

For Linux desktop packaging and system deps, see
[docs/linux-install.md](docs/linux-install.md). Project layout and architecture
live in [docs/overview.md](docs/overview.md) and
[docs/architecture.md](docs/architecture.md).

## What to change

- Prefer small, focused PRs that do one thing.
- Match the style of nearby code (vanilla JS ES modules in `app/unweave/web/`,
  Python under `app/unweave/`).
- Do not commit secrets, local caches (`.sound-razor/`, `.venv/`), build output
  (`dist/`), or large binaries.
- Keep user-facing docs in sync when behavior changes (`README.md`, `docs/`).

## Tests

Run the unit suite from the repo root:

```bash
# with the venv active, or pass the venv python explicitly
pytest
```

Add or update tests under `tests/` when you change behavior that already has
coverage, or when a bug fix can be locked in with a regression test.

## Pull requests

- Use a clear title that says what changed and why it matters.
- Link related issues.
- Describe how you tested the change.
- Expect review feedback; PRs into `main` go through the repository ruleset
  (linear history, pull-request merge path).

## Reporting bugs

Please include:

- Unweave version (or commit)
- OS
- Steps to reproduce
- Expected vs actual behavior
- Relevant logs or screenshots

## License

By contributing, you agree that your contributions are licensed under the same
[MIT License](LICENSE) as the project.
