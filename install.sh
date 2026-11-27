#!/usr/bin/env bash
# Install (or upgrade) Saint Directory (saintd) for the current user, on Linux or macOS.
# Your directory, settings, saved saints and downloaded voices are kept.
#   ./install.sh            installs with pipx when you have it, otherwise into a private environment
#   ./install.sh --no-pipx  always installs into the private environment
set -euo pipefail
cd "$(dirname "$0")"

USE_PIPX=1
for arg in "$@"; do
    case "$arg" in
        --no-pipx) USE_PIPX=0 ;;
        -h|--help) sed -n '2,5p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $arg (see ./install.sh --help)" >&2; exit 2 ;;
    esac
done

MACOS=0
[ "$(uname -s)" = "Darwin" ] && MACOS=1
if [ "$MACOS" = 1 ]; then
    GET_PYTHON="brew install python  (or the installer from python.org)"
else
    GET_PYTHON="sudo apt install python3 python3-venv"
fi

# Python 3.10 or newer: python3, or a newer python3.x when python3 is older (macOS's own is 3.9)
PY=""
for cand in python3 python3.14 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$cand" >/dev/null 2>&1 &&
        "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
        PY="$(command -v "$cand")"
        break
    fi
done
if [ -z "$PY" ]; then
    if command -v python3 >/dev/null 2>&1; then
        echo "Saint Directory needs Python 3.10 or newer (found $(python3 -V 2>&1)). Install it:  $GET_PYTHON" >&2
    else
        echo "Python 3 is required:  $GET_PYTHON" >&2
    fi
    exit 1
fi

# pip builds saintd inside this folder and leaves build/ behind. An old build/ would carry files that
# have since been removed from saintd into the new install, so start from a clean folder and tidy up after.
clean_build() { rm -rf build saint_directory.egg-info; }
clean_build
trap clean_build EXIT

PIPER_NOTE="Natural voices (Piper) could not be installed now; reading aloud uses your system voices.
You can add Piper later in Settings -> Voice & Reading aloud (Install Piper)."
VENV="$HOME/.local/share/saintd-venv"

if [ "$USE_PIPX" = 1 ] && command -v pipx >/dev/null 2>&1; then
    echo "Installing with pipx..."
    pipx install --force --python "$PY" .
    echo "Adding Piper for natural reading voices (about 60 MB)..."
    pipx inject --force saint-directory piper-tts >/dev/null 2>&1 || echo "$PIPER_NOTE"
    BIN_DIR="${PIPX_BIN_DIR:-$HOME/.local/bin}"
    PATH_HINT="run  pipx ensurepath  and open a new terminal"
    # A copy installed earlier without pipx is no longer used: remove it and its link.
    if [ -f "$VENV/pyvenv.cfg" ]; then
        if [ "$(readlink "$HOME/.local/bin/saintd" 2>/dev/null)" = "$VENV/bin/saintd" ]; then
            rm -f "$HOME/.local/bin/saintd"
        fi
        rm -rf "$VENV"
        echo "Removed the earlier copy in $VENV (saintd is now installed with pipx)."
    fi
else
    echo "Installing into $VENV"
    if ! "$PY" -m venv "$VENV" 2>/dev/null; then
        if [ "$MACOS" = 1 ]; then
            echo "Could not create a virtual environment with $PY. Install Python:  $GET_PYTHON" >&2
        else
            echo "Could not create a virtual environment. Run:  sudo apt install python3-venv" >&2
        fi
        exit 1
    fi
    "$VENV/bin/python" -m pip install --quiet --upgrade pip
    "$VENV/bin/python" -m pip install --quiet .
    echo "Adding Piper for natural reading voices (about 60 MB)..."
    "$VENV/bin/python" -m pip install --quiet piper-tts >/dev/null 2>&1 || echo "$PIPER_NOTE"
    BIN_DIR="$HOME/.local/bin"
    if [ "$MACOS" = 1 ]; then
        PATH_HINT="run  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.zshrc  and open a new terminal"
    else
        PATH_HINT="log out and back in, then open a new terminal"
    fi
    mkdir -p "$BIN_DIR"
    ln -sf "$VENV/bin/saintd" "$BIN_DIR/saintd"
fi

START="saintd"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) START="$BIN_DIR/saintd"
       echo "Note: $BIN_DIR is not on your PATH yet. To start saintd by name, $PATH_HINT." ;;
esac

if [ "$MACOS" = 0 ] && ! command -v pw-play >/dev/null 2>&1 && ! command -v paplay >/dev/null 2>&1 &&
    ! command -v aplay >/dev/null 2>&1; then
    echo "Note: no audio player was found; for reading aloud run:  sudo apt install pipewire-bin"
fi

echo
echo "Saint Directory is installed. Start it with:  $START"
echo "Press P on a saint to hear the life read aloud (Settings -> Voice & Reading aloud to choose a voice)."
