#!/usr/bin/env bash
set -euo pipefail

echo "===================================================="
echo "  Noryka AI Assistant — Termux & Linux Installer"
echo "===================================================="

VENV_DIR="${NORYKA_VENV_DIR:-$HOME/.noryka/venv}"

if [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *"com.termux"* ]]; then
    echo "[1/4] Detected Android / Termux environment."
    echo "      Installing required binary packages via pkg (no silent error masking)..."
    pkg update -y
    pkg install -y python git ripgrep clang libffi openssl \
        python-cryptography python-pillow python-psutil
    echo "[2/4] Creating virtual environment with --system-site-packages at $VENV_DIR ..."
    python3 -m venv --system-site-packages "$VENV_DIR"
else
    echo "[1/4] Detected standard Linux / POSIX environment."
    echo "[2/4] Creating virtual environment at $VENV_DIR ..."
    python3 -m venv "$VENV_DIR"
fi

# Activate the virtual environment (never mutate system pip on Termux)
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "[3/4] Preparing Noryka runtime directories at ~/.noryka ..."
mkdir -p "$HOME/.noryka/sessions" "$HOME/.noryka/memories" "$HOME/.noryka/skills" "$HOME/.noryka/logs"
chmod 700 "$HOME/.noryka"

echo "[4/4] Installing Noryka with [termux] extras (Telegram, Bale, MCP, Core)..."
pip install --no-build-isolation -e ".[termux]"

if [ -n "${PREFIX:-}" ] && [ -d "$PREFIX/bin" ]; then
    ln -sf "$VENV_DIR/bin/noryka" "$PREFIX/bin/noryka"
    ln -sf "$VENV_DIR/bin/noryka-agent" "$PREFIX/bin/noryka-agent"
fi

echo "===================================================="
echo "  Noryka installed successfully!"
echo "  - Run smoke & live tests: $VENV_DIR/bin/pytest tests/test_noryka_smoke.py"
echo "  - Run interactive chat:   $VENV_DIR/bin/noryka chat"
echo "  - Run Telegram/Bale bot:  $VENV_DIR/bin/noryka gateway run"
echo "  - Run Web Dashboard UI:   $VENV_DIR/bin/noryka dashboard --port 8080 --skip-build"
echo "  - Open Gateway Webapp:    $VENV_DIR/bin/noryka webapp --status"
echo "===================================================="
