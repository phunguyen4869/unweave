#!/usr/bin/env bash
# Unweave — macOS installer (unsigned)
#
# The macOS counterpart to install-linux.sh. Builds a venv with `uv` (or venv),
# installs the app, writes a launcher, and optionally an unsigned .app for the
# Dock. No code signing or notarization — Gatekeeper may require right-click →
# Open the first time you launch the .app.
#
# Usage:
#   ./install-macos.sh                 # install under ~/Library/Application Support/Unweave
#   ./install-macos.sh --prefix DIR    # install somewhere else
#   ./install-macos.sh --full          # also install PyTorch/audio-separator now
#   ./install-macos.sh --no-deps       # skip the pip install (reinstall code only)
#   ./install-macos.sh --uninstall     # remove the app and launcher (keeps models + songs)
#   ./install-macos.sh --purge         # uninstall + remove model cache and settings
#   ./install-macos.sh --help
#
# Picks a Python 3.11-3.14 itself (onnxruntime has no 3.15 wheels yet);
# PYTHON=/path/to/python3.13 ./install-macos.sh overrides that choice.

set -euo pipefail

APP_NAME="Unweave"
PACKAGE_NAME="unweave"
DEFAULT_PREFIX="$HOME/Library/Application Support/Unweave"
# Prefer /usr/local/bin when writable (common on Intel Homebrew); else ~/.local/bin.
if [ -d /usr/local/bin ] && [ -w /usr/local/bin ]; then
    DEFAULT_BIN_DIR="/usr/local/bin"
else
    DEFAULT_BIN_DIR="$HOME/.local/bin"
fi
BIN_DIR="$DEFAULT_BIN_DIR"
APPLICATIONS_DIR="$HOME/Applications"
APP_BUNDLE="$APPLICATIONS_DIR/Unweave.app"

# Per-user data the app creates at runtime (matches app_data_dir() on Darwin).
CONFIG_DIR="$HOME/Library/Application Support/Unweave"
PROJECTS_DIR="$HOME/Music/Unweave"

PREFIX="$DEFAULT_PREFIX"
MODE="install"
WITH_DEPS="base"

usage() {
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
Install one — brew install python@$UV_FALLBACK_PYTHON, or python.org — then run this script again."
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
APP_SRC="$REPO_ROOT/app"
PYPROJECT="$REPO_ROOT/pyproject.toml"
ICON_SRC="$REPO_ROOT/docs/landing-page/assets/icon-256.png"

# Resolve launcher path: prefer an existing install's bin, else DEFAULT_BIN_DIR.
resolve_bin_dir() {
    if [ -x "$BIN_DIR/unweave" ]; then
        return
    fi
    if [ -x "$HOME/.local/bin/unweave" ]; then
        BIN_DIR="$HOME/.local/bin"
    elif [ -x "/usr/local/bin/unweave" ]; then
        BIN_DIR="/usr/local/bin"
    fi
}

uninstall() {
    local quiet="${1:-}"
    say "Uninstalling $APP_NAME…"
    resolve_bin_dir
    # Default layout shares Application Support/Unweave with settings + models —
    # remove only the install tree, never models/ or ui.json here.
    if [ -d "$PREFIX" ]; then
        same_as_config=0
        if [ -d "$CONFIG_DIR" ] && [ "$(cd "$PREFIX" && pwd -P)" = "$(cd "$CONFIG_DIR" && pwd -P)" ]; then
            same_as_config=1
        fi
        if [ "$same_as_config" -eq 1 ]; then
            rm -rf "$PREFIX/app" "$PREFIX/.venv"
            rm -f "$PREFIX/pyproject.toml" "$PREFIX/README.md" "$PREFIX/LICENSE"
            echo "Kept settings/models under $PREFIX"
        else
            rm -rf "$PREFIX"
        fi
    fi
    rm -f "$BIN_DIR/unweave" "$HOME/.local/bin/unweave" "/usr/local/bin/unweave"
    rm -rf "$APP_BUNDLE"
    ok "Removed the app, launcher and Dock .app (if present)."
    if [ "$quiet" != "quiet" ]; then
        echo
        echo "Kept (delete these yourself if you want a clean slate, or use --purge):"
        echo "  $CONFIG_DIR/ui.json   (settings)"
        echo "  $CONFIG_DIR/models    (AI models, ~455 MB)"
        echo "  $PROJECTS_DIR         (your separated songs)"
    fi
}

purge() {
    uninstall quiet
    echo
    say "Purging model cache and settings…"
    local removed=0
    if [ -e "$CONFIG_DIR/models" ]; then
        rm -rf "$CONFIG_DIR/models"
        echo "Removed $CONFIG_DIR/models"
        removed=1
    fi
    if [ -e "$CONFIG_DIR/ui.json" ]; then
        rm -f "$CONFIG_DIR/ui.json"
        echo "Removed $CONFIG_DIR/ui.json"
        removed=1
    fi
    if [ "$removed" -eq 0 ]; then
        echo "Nothing else to remove (models/settings were already gone)."
    fi
    echo
    echo "Kept:"
    echo "  $PROJECTS_DIR (your separated songs)"
}

write_app_bundle() {
    # Unsigned .app that runs the same launcher. Gatekeeper: right-click → Open once.
    mkdir -p "$APP_BUNDLE/Contents/MacOS" "$APP_BUNDLE/Contents/Resources"
    if [ -f "$ICON_SRC" ]; then
        cp -a "$ICON_SRC" "$APP_BUNDLE/Contents/Resources/icon.png"
    fi
    cat > "$APP_BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>
  <string>unweave</string>
  <key>CFBundleIdentifier</key>
  <string>com.um1chc5.unweave</string>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>1.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST
    cat > "$APP_BUNDLE/Contents/MacOS/unweave" <<EOF
#!/usr/bin/env bash
exec "$BIN_DIR/unweave" "\$@"
EOF
    chmod +x "$APP_BUNDLE/Contents/MacOS/unweave"
    ok "Dock app (unsigned): $APP_BUNDLE"
}

install() {
    say "$APP_NAME — macOS installer (unsigned)"
    echo

    [ "$(uname -s)" = "Darwin" ] || die "This installer is for macOS only. Use install-linux.sh on Linux."
    [ -f "$PYPROJECT" ] || die "Can't find pyproject.toml at $PYPROJECT. Run this from a full checkout."
    [ -d "$APP_SRC" ] || die "Can't find the app/ folder at $APP_SRC. Run this from a full checkout."

    resolve_python
    ok "Python: $("$PYTHON" --version 2>&1) ($PYTHON)"

    UV="$(command -v uv || true)"
    if [ -z "$UV" ]; then
        warn "uv not found — falling back to python -m venv + pip."
        if ! "$PYTHON" -m venv --help >/dev/null 2>&1; then
            die "Neither uv nor the venv module is available. Install uv (https://astral.sh/uv)."
        fi
    fi

    # No --system-site-packages: Cocoa/PyObjC arrive via pywebview's pip deps.
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
            "$UV" venv --python "$PYTHON" "$VENV"
        else
            "$PYTHON" -m venv "$VENV"
        fi
    fi
    VPIP="$VENV/bin/python"

    say "Copying app files…"
    rm -rf "$PREFIX/app"
    mkdir -p "$PREFIX/app"
    cp -a "$APP_SRC/unweave" "$PREFIX/app/unweave"
    cp -a "$APP_SRC/ui_entrypoint.py" "$PREFIX/app/ui_entrypoint.py"
    cp -a "$PYPROJECT" "$PREFIX/app/pyproject.toml"
    cp -a "$PYPROJECT" "$PREFIX/pyproject.toml"
    [ -f "$REPO_ROOT/README.md" ] && cp -a "$REPO_ROOT/README.md" "$PREFIX/README.md"
    [ -f "$REPO_ROOT/LICENSE" ] && cp -a "$REPO_ROOT/LICENSE" "$PREFIX/LICENSE"

    case "$WITH_DEPS" in
        none)
            warn "Skipping package install (--no-deps)."
            ;;
        *)
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

    mkdir -p "$BIN_DIR"
    cat > "$BIN_DIR/unweave" <<EOF
#!/usr/bin/env bash
# Generated by installer/install-macos.sh — do not edit; re-run the installer.
# Native Cocoa/WKWebView window by default; UNWEAVE_BROWSER=1 opens a browser tab.
set -euo pipefail
APP="$PREFIX"
export PATH="/opt/homebrew/bin:/usr/local/bin:\$HOME/.local/bin:\$PATH"
cd "\$APP/app"
exec "\$APP/.venv/bin/python" "\$APP/app/ui_entrypoint.py" "\$@"
EOF
    chmod +x "$BIN_DIR/unweave"
    ok "Launcher: $BIN_DIR/unweave"

    mkdir -p "$APPLICATIONS_DIR"
    write_app_bundle

    echo
    ok "Installed to $PREFIX"
    echo
    if [ "$WITH_DEPS" != "full" ]; then
        echo "On first launch the app offers to download FFmpeg and the separation"
        echo "engine (~1.7 GB) from its own setup screen. Until then, Library and"
        echo "Separate stay disabled. Homebrew ffmpeg on PATH also satisfies setup."
        echo
    fi
    case ":$PATH:" in
        *":$BIN_DIR:"*) ;;
        *) warn "$BIN_DIR is not on your PATH — launch with: $BIN_DIR/unweave" ;;
    esac
    echo "Start with: unweave"
    echo "Or open $APP_BUNDLE (unsigned — right-click → Open the first time)."
    echo "Uninstall with: $SCRIPT_DIR/install-macos.sh --uninstall"
    echo "Fully clean (keeps songs): $SCRIPT_DIR/install-macos.sh --purge"
}

case "$MODE" in
    uninstall) uninstall ;;
    purge) purge ;;
    install) install ;;
esac
