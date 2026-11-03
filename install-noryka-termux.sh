#!/usr/bin/env bash
set -euo pipefail

echo "===================================================="
echo "  Noryka AI Assistant — Termux & Linux Installer"
echo "===================================================="

VENV_DIR="${NORYKA_VENV_DIR:-$HOME/.noryka/venv}"

if [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *"com.termux"* ]]; then
    echo "[1/4] Detected Android / Termux environment."
    echo "      Installing required binary packages via pkg (no silent error masking)..."
    if [ "${NORYKA_SKIP_PKG_UPDATE:-0}" != "1" ]; then
        pkg update -y
    fi
    pkg install -y python git ripgrep clang libffi openssl rust \
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

echo "[4/4] Preparing isolated build backend in the virtual environment..."
python -m pip install --upgrade "setuptools>=68.0.0" wheel setuptools-rust
if [ -n "${TERMUX_VERSION:-}" ] || [[ "${PREFIX:-}" == *"com.termux"* ]]; then
    if [ -z "${ANDROID_API_LEVEL:-}" ]; then
        if command -v getprop >/dev/null 2>&1; then
            if ! ANDROID_API_LEVEL="$(getprop ro.build.version.sdk 2>/dev/null)"; then
                ANDROID_API_LEVEL=""
            fi
        fi
    fi
    case "${ANDROID_API_LEVEL:-}" in
        ''|*[!0-9]*) ANDROID_API_LEVEL=24 ;;
    esac
    if [ "$ANDROID_API_LEVEL" -lt 24 ]; then ANDROID_API_LEVEL=24; fi
    export ANDROID_API_LEVEL
    case "$(uname -m)" in
        aarch64|arm64) export CARGO_BUILD_TARGET="${CARGO_BUILD_TARGET:-aarch64-linux-android}" ;;
    esac
    echo "      Android API level: $ANDROID_API_LEVEL"
    echo "      Rust target: ${CARGO_BUILD_TARGET:-auto}"
    rustc --version
    cargo --version
    echo "      Building maturin for Android/Bionic (required by pydantic-core)..."
    CARGO_BUILD_JOBS="${CARGO_BUILD_JOBS:-2}" \
        python -m pip install --no-build-isolation --no-binary=maturin "maturin>=1.15,<2"
    maturin --version
fi
python -c "import setuptools, wheel; print('Build backend ready:', setuptools.__version__, wheel.__version__)"

echo "      Installing Noryka with [termux] extras (Telegram, Bale, MCP, Core)..."
python -m pip install --no-build-isolation -e ".[termux]"

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
