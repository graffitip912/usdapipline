#!/usr/bin/env bash
# USDA Grain Pipeline — Environment Setup Script (Linux/macOS)
# Usage: bash scripts/setup_env.sh
# Prerequisites: Python 3.10+, Node.js 18+

set -e
cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

echo "=== USDA Grain Pipeline Setup ==="

# --- Python Backend ---
echo -e "\n[1/5] Python venv..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "  Created .venv"
else
    echo "  .venv already exists"
fi

echo "[2/5] Installing Python dependencies..."
.venv/bin/pip install -e . --quiet
echo "  Done"

# --- Environment Variables ---
echo "[3/5] Environment config..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "  Created .env from .env.example"
    echo "  >> API keys must be configured in .env <<"
else
    echo "  .env already exists"
fi

# --- Dashboard ---
echo "[4/5] Dashboard dependencies..."
cd dashboard
if [ ! -f ".env.local" ] && [ -f ".env.example" ]; then
    cp .env.example .env.local
    echo "  Created dashboard/.env.local"
fi
npm install --silent 2>/dev/null
echo "  Done"
cd "$PROJECT_ROOT"

# --- Data directories ---
echo "[5/5] Data directories..."
.venv/bin/python -c "from common.storage import ensure_dirs; ensure_dirs(); print('  Created')"

# --- Optional: Tesseract OCR ---
echo -e "\n--- Optional Tools ---"
if command -v tesseract &>/dev/null; then
    echo "  Tesseract: $(which tesseract)"
else
    echo "  Tesseract: NOT INSTALLED (apt install tesseract-ocr / brew install tesseract)"
fi

# --- Verify ---
echo -e "\n=== Verification ==="
.venv/bin/python -c "from api.main import app; print('  API module: OK')"
cd dashboard && npm run build --silent 2>/dev/null && echo "  Dashboard build: OK" || echo "  Dashboard build: FAILED"
cd "$PROJECT_ROOT"

echo -e "\n=== Setup Complete ==="
echo "Next steps:"
echo "  1. Edit .env with API keys (NASS_QUICKSTATS_API_KEY, FAS_OPENDATA_API_KEY)"
echo "  2. .venv/bin/python -m uvicorn api.main:app --reload    # API :8000"
echo "  3. cd dashboard && npm run dev                           # Dashboard :3000"
echo "  4. .venv/bin/python -m collector.run --source all        # Collectors"
