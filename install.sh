#!/usr/bin/env bash
# Install (or upgrade) Saint Directory (saintd) for the current user.
# Your directory, settings, saved saints and downloaded voices are kept.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "Python 3 is required:  sudo apt install python3 python3-venv" >&2
    exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    echo "Saint Directory needs Python 3.10 or newer (found $(python3 -V))." >&2
    exit 1
fi

PIPER_NOTE="Natural voices (Piper) could not be installed now; reading aloud uses your system voices.
You can add Piper later in Settings -> Voice & Reading aloud (Install Piper)."

if command -v pipx >/dev/null 2>&1; then
    echo "Installing with pipx..."
    pipx install --force .
    echo "Adding Piper for natural reading voices (about 60 MB)..."
    pipx inject --force saint-directory piper-tts >/dev/null 2>&1 || echo "$PIPER_NOTE"
else
    VENV="$HOME/.local/share/saintd-venv"
    echo "pipx not found - installing into $VENV"
    if ! python3 -m venv "$VENV" 2>/dev/null; then
        echo "Could not create a virtual environment. Run:  sudo apt install python3-venv" >&2
        exit 1
    fi
    "$VENV/bin/python" -m pip install --quiet --upgrade pip
    "$VENV/bin/python" -m pip install --quiet .
    echo "Adding Piper for natural reading voices (about 60 MB)..."
    "$VENV/bin/python" -m pip install --quiet piper-tts >/dev/null 2>&1 || echo "$PIPER_NOTE"
    mkdir -p "$HOME/.local/bin"
    ln -sf "$VENV/bin/saintd" "$HOME/.local/bin/saintd"
    case ":$PATH:" in
        *":$HOME/.local/bin:"*) ;;
        *) echo "Note: add ~/.local/bin to your PATH (usually logging out and back in, then opening a new terminal, does it)." ;;
    esac
fi

if ! command -v pw-play >/dev/null 2>&1 && ! command -v paplay >/dev/null 2>&1 && ! command -v aplay >/dev/null 2>&1; then
    echo "Note: no audio player was found; for reading aloud run:  sudo apt install pipewire-bin"
fi

echo
echo "Saint Directory is installed. Start it with:  saintd"
echo "Press P on a saint to hear the life read aloud (Settings -> Voice & Reading aloud to choose a voice)."
