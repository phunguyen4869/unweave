#!/usr/bin/env bash
# Unweave — Linux installer
#
# The Linux counterpart to bootstrap.ps1 + Unweave.nsis. The Windows installer
# ships a prebuilt embedded Python runtime; Linux has no equivalent (a frozen
# interpreter would have to be built per distro), so this script instead builds a
# venv with `uv` and installs the app into it, then writes a launcher and a
# .desktop entry. Like the Windows installer it deliberately does NOT download the
# heavy stuff (FFmpeg, PyTorch/audio-separator ~1.6 GB): those are pulled by the
# app's own first-run setup screen, behind explicit consent.
#
# Usage:
#   ./install-linux.sh                 # install to ~/.local/share/unweave
#   ./install-linux.sh --prefix DIR    # install somewhere else
#   ./install-linux.sh --full          # also install PyTorch/audio-separator now
#   ./install-linux.sh --no-deps       # skip the pip install (reinstall code only)
#   ./install-linux.sh --uninstall     # remove the app (keeps models + your songs)
#   ./install-linux.sh --purge         # uninstall + remove model cache and settings
#   ./install-linux.sh --help
#
# Picks a Python 3.11-3.14 itself (onnxruntime has no 3.15 wheels yet);
# PYTHON=/path/to/python3.13 ./install-linux.sh overrides that choice.

set -euo pipefail

APP_NAME="Unweave"
PACKAGE_NAME="unweave"
DEFAULT_PREFIX="$HOME/.local/share/unweave"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons"

# Per-user data the app itself creates at runtime (matches app_data_dir() on Linux).
# Kept on uninstall: the model cache alone is ~455 MB of downloaded weights, and
# the projects folder is the user's own separated songs.
CONFIG_DIR="$HOME/.local/share/unweave"
PROJECTS_DIR="$HOME/Music/Unweave"

PREFIX="$DEFAULT_PREFIX"
MODE="install"
WITH_DEPS="base"

usage() {
    # Print this script's leading comment block (after the shebang) as help text,
    # so --help can never drift out of sync with the header.
    awk 'NR > 1 { if (/^#/) { sub(/^# ?/, ""); print } else exit }' "$0"
    exit 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX="${2:?--prefix needs a directory}"; shift 2 ;;
        --full) WITH_DEPS="full"; shift ;;
        --no-deps) WITH_DEPS="none"; shift ;;
        --uninstall) MODE="uninstall"; shift ;;
        --purge) MODE="purge"; shift ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
done

say()  { printf '\033[1;36m%s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m%s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m%s\033[0m\n' "$*" >&2; exit 1; }

# Supported interpreters, newest first. The upper bound is onnxruntime's: it
# publishes no wheels past CPython 3.14, so a 3.15 venv installs the app fine and
# then dies at the separation stage with "No matching distribution found".
PYTHON_RANGE="3.11-3.14"
PYTHON_CANDIDATES="python3.14 python3.13 python3.12 python3.11"
UV_FALLBACK_PYTHON="3.13"

python_ok() {
    command -v "$1" >/dev/null 2>&1 || return 1
    "$1" - <<'EOF' >/dev/null 2>&1
import sys
raise SystemExit(0 if (3, 11) <= sys.version_info < (3, 15) else 1)
EOF
}

# Pick an interpreter: an explicit $PYTHON always wins (and is checked, not
# silently replaced), then python3, then the newest supported pythonX.Y on PATH,
# then one uv fetches for us.
resolve_python() {
    if [ -n "${PYTHON:-}" ]; then
        command -v "$PYTHON" >/dev/null 2>&1 || die "PYTHON=$PYTHON not found."
        python_ok "$PYTHON" || die "PYTHON=$PYTHON is $("$PYTHON" --version 2>&1), outside $PYTHON_RANGE."
        return
    fi
    for candidate in python3 $PYTHON_CANDIDATES; do
        if python_ok "$candidate"; then
            PYTHON="$(command -v "$candidate")"
            return
        fi
    done
    if command -v uv >/dev/null 2>&1; then
        say "No supported Python on PATH — asking uv for $UV_FALLBACK_PYTHON…"
        if uv python install "$UV_FALLBACK_PYTHON" >/dev/null 2>&1; then
            PYTHON="$(uv python find "$UV_FALLBACK_PYTHON" 2>/dev/null || true)"
            if [ -n "$PYTHON" ] && python_ok "$PYTHON"; then
                return
            fi
        fi
    fi
    die "No supported Python found. Unweave needs $PYTHON_RANGE (onnxruntime ships no wheels for 3.15+).
Install one from your distro (e.g. apt install python$UV_FALLBACK_PYTHON python$UV_FALLBACK_PYTHON-venv) and run this script again."
}

# The repo root is this script's parent; the app lives in app/ and the packaging
# metadata (pyproject.toml) at the root, exactly as the NSIS installer reads them.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
APP_SRC="$REPO_ROOT/app"
PYPROJECT="$REPO_ROOT/pyproject.toml"
ICON_SRC="$REPO_ROOT/docs/landing-page/assets/icon-256.png"

refresh_desktop_db() {
    command -v update-desktop-database >/dev/null 2>&1 &&
        update-desktop-database "$DESKTOP_DIR" >/dev/null 2>&1 || true
}

uninstall() {
    local quiet="${1:-}"
    say "Uninstalling $APP_NAME…"
    # PREFIX defaults to the same folder as CONFIG_DIR. Spec 07: uninstall keeps
    # settings (ui.json) and models; only --purge removes those.
    if [ -d "$PREFIX" ]; then
        if [ -f "$PREFIX/ui.json" ] && [ "$(cd "$PREFIX" && pwd -P)" = "$(cd "$CONFIG_DIR" && pwd -P)" ]; then
            saved="$(mktemp)"
            mv "$PREFIX/ui.json" "$saved"
            rm -rf "$PREFIX"
            mkdir -p "$PREFIX"
            mv "$saved" "$PREFIX/ui.json"
            echo "Kept $PREFIX/ui.json (settings)"
        else
            rm -rf "$PREFIX"
        fi
    fi
    rm -f "$BIN_DIR/unweave"
    rm -f "$DESKTOP_DIR/unweave.desktop"
    rm -f "$ICON_DIR/unweave.png"
    refresh_desktop_db
    ok "Removed the app, launcher and menu entry."
    if [ "$quiet" != "quiet" ]; then
        echo
        echo "Kept (delete these yourself if you want a clean slate, or use --purge):"
        echo "  $CONFIG_DIR/ui.json   (settings)"
        echo "  $CONFIG_DIR/models    (AI models, ~455 MB)"
        echo "  $PROJECTS_DIR         (your separated songs)"
    fi
}

purge() {
    # Same as uninstall, then also drop the model cache and settings. Never touches
    # the music/projects folder — that is the user's own separated songs.
    # Call uninstall quietly so we don't claim settings/models were kept.
    uninstall quiet
    echo
    say "Purging model cache and settings…"
    local removed=0
    if [ -e "$CONFIG_DIR/models" ]; then
        rm -rf "$CONFIG_DIR/models"
        echo "Removed $CONFIG_DIR/models"
        removed=1
    fi
    # Older installs may have used ~/.cache/unweave/models before app_data_dir was fixed.
    if [ -e "$HOME/.cache/unweave/models" ]; then
        rm -rf "$HOME/.cache/unweave/models"
        echo "Removed $HOME/.cache/unweave/models"
        rmdir "$HOME/.cache/unweave" 2>/dev/null || true
        removed=1
    fi
    if [ -e "$CONFIG_DIR/ui.json" ]; then
        rm -f "$CONFIG_DIR/ui.json"
        echo "Removed $CONFIG_DIR/ui.json"
        removed=1
    fi
    if [ "$PREFIX" != "$CONFIG_DIR" ]; then
        rmdir "$CONFIG_DIR" 2>/dev/null || true
    fi
    if [ "$removed" -eq 0 ]; then
        echo "Nothing else to remove (models/settings were already gone)."
    fi
    echo
    echo "Kept:"
    echo "  $PROJECTS_DIR (your separated songs)"
}

install() {
    say "$APP_NAME — Linux installer"
    echo

    [ -f "$PYPROJECT" ] || die "Can't find pyproject.toml at $PYPROJECT. Run this from a full checkout."
    [ -d "$APP_SRC" ] || die "Can't find the app/ folder at $APP_SRC. Run this from a full checkout."

    # --- 1. Python ---------------------------------------------------------
    resolve_python
    ok "Python: $("$PYTHON" --version 2>&1) ($PYTHON)"

    # --- 2. uv -------------------------------------------------------------
    # Preferred, and what the Windows bootstrap uses too. pip works as a fallback
    # so the script still runs on a machine with no network access to astral.sh.
    UV="$(command -v uv || true)"
    if [ -z "$UV" ]; then
        warn "uv not found — falling back to python -m venv + pip."
        if ! "$PYTHON" -m venv --help >/dev/null 2>&1; then
            die "Neither uv nor the venv module is available. Install uv (https://astral.sh/uv) or python3-venv."
        fi
    fi

    # --- 3. venv -----------------------------------------------------------
    # --system-site-packages is what makes the native window work: pywebview's GTK
    # backend imports gi/WebKit2, which distros ship as system packages and which
    # cannot be pip-installed into a venv. Without it the app silently falls back
    # to a browser tab. See docs/linux-install.md.
    mkdir -p "$PREFIX"
    VENV="$PREFIX/.venv"
    # A venv is welded to the interpreter that created it, so one built on an
    # unsupported Python can never install the separation engine. Rebuild it
    # rather than reusing it into the same failure.
    if [ -x "$VENV/bin/python" ] && ! python_ok "$VENV/bin/python"; then
        warn "Existing venv runs $("$VENV/bin/python" --version 2>&1), outside $PYTHON_RANGE — rebuilding it."
        rm -rf "$VENV"
    fi
    if [ -x "$VENV/bin/python" ]; then
        say "Reusing the existing virtual environment at $VENV"
    else
        say "Creating virtual environment at $VENV"
        if [ -n "$UV" ]; then
            "$UV" venv --python "$PYTHON" --system-site-packages "$VENV"
        else
            "$PYTHON" -m venv --system-site-packages "$VENV"
        fi
    fi
    VPIP="$VENV/bin/python"

    # --- 4. app code -------------------------------------------------------
    # The layout mirrors the repo exactly, because the code depends on it:
    # pyproject.toml declares `[tool.setuptools.packages.find] where = ["app"]`,
    # and setup_env.py resolves its own install dir as the parent of the
    # unweave package (so it looks for pyproject.toml beside it, and drops
    # FFmpeg there). Flattening unweave/ to the prefix root — the obvious
    # thing to do — breaks both: `uv pip install -e` fails with
    # "error in 'egg_base' option: 'app' does not exist", and first-run setup
    # then can't read the requirements it is supposed to install.
    say "Copying app files…"
    rm -rf "$PREFIX/app"
    mkdir -p "$PREFIX/app"
    cp -a "$APP_SRC/unweave" "$PREFIX/app/unweave"
    cp -a "$APP_SRC/ui_entrypoint.py" "$PREFIX/app/ui_entrypoint.py"
    cp -a "$PYPROJECT" "$PREFIX/app/pyproject.toml"
    cp -a "$PYPROJECT" "$PREFIX/pyproject.toml"
    [ -f "$REPO_ROOT/README.md" ] && cp -a "$REPO_ROOT/README.md" "$PREFIX/README.md"
    [ -f "$REPO_ROOT/LICENSE" ] && cp -a "$REPO_ROOT/LICENSE" "$PREFIX/LICENSE"

    # --- 5. Python packages ------------------------------------------------
    case "$WITH_DEPS" in
        none)
            warn "Skipping package install (--no-deps)."
            ;;
        *)
            # pywebview alone: enough to open the window. The audio stack is left
            # to the app's first-run setup, matching the Windows installer, unless
            # --full was given.
            say "Installing the app package (pywebview)…"
            if [ -n "$UV" ]; then
                "$UV" pip install --python "$VPIP" -e "$PREFIX"
            else
                "$VPIP" -m pip install --disable-pip-version-check -e "$PREFIX"
            fi
            if [ "$WITH_DEPS" = "full" ]; then
                say "Installing the audio stack (PyTorch etc.) — this is the big one…"
                if [ -n "$UV" ]; then
                    "$UV" pip install --python "$VPIP" -e "$PREFIX[full]"
                else
                    "$VPIP" -m pip install --disable-pip-version-check -e "$PREFIX[full]"
                fi
            fi
            ok "Python packages installed."
            ;;
    esac

    # --- 6. launcher -------------------------------------------------------
    # Up to 1.2.2 the app was "SoundRazer Desktop"; drop its launcher and menu entry.
    rm -f "$BIN_DIR/soundrazer" "$DESKTOP_DIR/soundrazer.desktop" "$ICON_DIR/soundrazer.png"
    mkdir -p "$BIN_DIR"
    cat > "$BIN_DIR/unweave" <<EOF
#!/usr/bin/env bash
# Generated by installer/install-linux.sh — do not edit; re-run the installer.
# Native GTK/WebKit window by default; UNWEAVE_BROWSER=1 opens a browser tab.
set -euo pipefail
APP="$PREFIX"
export PATH="\$HOME/.local/bin:\$PATH"
cd "\$APP/app"
exec "\$APP/.venv/bin/python" "\$APP/app/ui_entrypoint.py" "\$@"
EOF
    chmod +x "$BIN_DIR/unweave"
    ok "Launcher: $BIN_DIR/unweave"

    # --- 7. icon + menu entry ---------------------------------------------
    mkdir -p "$ICON_DIR" "$DESKTOP_DIR"
    if [ -f "$ICON_SRC" ]; then
        cp -a "$ICON_SRC" "$ICON_DIR/unweave.png"
        ICON="$ICON_DIR/unweave.png"
    else
        warn "Icon not found at $ICON_SRC; the menu entry will use a generic icon."
        ICON="audio-x-generic"
    fi
    cat > "$DESKTOP_DIR/unweave.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$APP_NAME
Comment=AI audio stem separation (local, native window)
Exec=$BIN_DIR/unweave
Icon=$ICON
Terminal=false
Categories=AudioVideo;Audio;
StartupNotify=false
EOF
    refresh_desktop_db
    ok "Menu entry: $DESKTOP_DIR/unweave.desktop"

    # --- 8. report ---------------------------------------------------------
    echo
    ok "Installed to $PREFIX"
    echo
    if [ "$WITH_DEPS" != "full" ]; then
        echo "On first launch the app offers to download FFmpeg and the separation"
        echo "engine (~1.7 GB) from its own setup screen. Until then, Library and"
        echo "Separate stay disabled."
        echo
    fi
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) warn "$BIN_DIR is not on your PATH — launch with: $BIN_DIR/unweave" ;;
    esac
    echo "Start it from your applications menu, or run: unweave"
    echo "Uninstall with: $SCRIPT_DIR/install-linux.sh --uninstall"
    echo "Fully clean (keeps songs): $SCRIPT_DIR/install-linux.sh --purge"
}

case "$MODE" in
    uninstall) uninstall ;;
    purge) purge ;;
    install) install ;;
esac
