#!/usr/bin/env bash
# install.sh — Install flow-py CLI
# Usage: bash install.sh [--venv] [--dev]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/.flow-py/venv"

USE_VENV=0
DEV_MODE=0
for arg in "$@"; do
    case "$arg" in
        --venv) USE_VENV=1 ;;
        --dev)  DEV_MODE=1 ;;
    esac
done

echo "=== flow-py installer ==="
echo "Source: $SCRIPT_DIR"

# ── Check Python ──────────────────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "❌ python3 not found. Install Python 3.10+ first."
    exit 1
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python: $PY_VER"

# ── Install in venv or system ─────────────────────────────
if [[ $USE_VENV -eq 1 ]]; then
    echo "Creating venv at $VENV_DIR …"
    python3 -m venv "$VENV_DIR"
    PIP="$VENV_DIR/bin/pip"
    PYTHON="$VENV_DIR/bin/python"

    # Wrapper script
    BIN_DIR="$HOME/.local/bin"
    mkdir -p "$BIN_DIR"
    cat > "$BIN_DIR/flow" <<EOF
#!/usr/bin/env bash
exec "$VENV_DIR/bin/flow" "\$@"
EOF
    chmod +x "$BIN_DIR/flow"
    echo "Wrapper created at $BIN_DIR/flow"
else
    PIP="pip3"
    PYTHON="python3"
fi

# ── pip install ───────────────────────────────────────────
if [[ $DEV_MODE -eq 1 ]]; then
    echo "Installing in dev/editable mode …"
    $PIP install -e "$SCRIPT_DIR[dev]" --quiet
else
    $PIP install "$SCRIPT_DIR" --quiet
fi

# ── Playwright browsers ───────────────────────────────────
echo "Installing Playwright Chromium …"
$PYTHON -m playwright install chromium --with-deps 2>/dev/null || \
    $PYTHON -m playwright install chromium

# ── Done ─────────────────────────────────────────────────
echo ""
echo "✅ flow-py installed!"
echo ""
echo "Next steps:"
echo "  flow login                          # Authenticate with Google (one-time)"
echo "  flow generate image 'your prompt'   # Generate an image"
echo "  flow generate video 'your prompt'   # Generate a video"
echo "  flow batch prompts.txt              # Process a batch file"
echo "  flow --help                         # Full command reference"
echo ""
if [[ $USE_VENV -eq 1 ]]; then
    echo "Note: venv wrapper installed at $BIN_DIR/flow"
    echo "Make sure $BIN_DIR is in your PATH."
fi
