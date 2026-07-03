# USDA Grain Pipeline — Environment Setup Script (Windows)
# Usage: .\scripts\setup_env.ps1
# Prerequisites: Python 3.10+, Node.js 18+

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

Write-Host "=== USDA Grain Pipeline Setup ===" -ForegroundColor Cyan

# --- Python Backend ---
Write-Host "`n[1/5] Python venv..." -ForegroundColor Yellow
if (-not (Test-Path ".venv")) {
    python -m venv .venv
    Write-Host "  Created .venv"
} else {
    Write-Host "  .venv already exists"
}

Write-Host "[2/5] Installing Python dependencies..." -ForegroundColor Yellow
& .\.venv\Scripts\pip.exe install -e . --quiet
Write-Host "  Done"

# --- Environment Variables ---
Write-Host "[3/5] Environment config..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "  Created .env from .env.example"
    Write-Host "  >> API keys must be configured in .env <<" -ForegroundColor Red
} else {
    Write-Host "  .env already exists"
}

# --- Dashboard ---
Write-Host "[4/5] Dashboard dependencies..." -ForegroundColor Yellow
Set-Location "dashboard"
if (-not (Test-Path ".env.local")) {
    if (Test-Path ".env.example") {
        Copy-Item ".env.example" ".env.local"
        Write-Host "  Created dashboard/.env.local"
    }
}
npm install --silent 2>$null
Write-Host "  Done"
Set-Location $ProjectRoot

# --- Data directories ---
Write-Host "[5/5] Data directories..." -ForegroundColor Yellow
& .\.venv\Scripts\python.exe -c "from common.storage import ensure_dirs; ensure_dirs(); print('  Created')"

# --- Optional: Tesseract OCR ---
Write-Host "`n--- Optional Tools ---" -ForegroundColor DarkGray
try {
    $tesseract = Get-Command tesseract -ErrorAction Stop
    Write-Host "  Tesseract: $($tesseract.Source)" -ForegroundColor Green
} catch {
    Write-Host "  Tesseract: NOT INSTALLED (install from https://github.com/UB-Mannheim/tesseract/wiki)" -ForegroundColor DarkGray
}

# --- Verify ---
Write-Host "`n=== Verification ===" -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -c "from api.main import app; print('  API module: OK')"
Set-Location "dashboard"
$buildResult = npm run build 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "  Dashboard build: OK" -ForegroundColor Green
} else {
    Write-Host "  Dashboard build: FAILED" -ForegroundColor Red
}
Set-Location $ProjectRoot

Write-Host "`n=== Setup Complete ===" -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "  1. Edit .env with API keys (NASS_QUICKSTATS_API_KEY, FAS_OPENDATA_API_KEY)"
Write-Host "  2. python -m uvicorn api.main:app --reload    # API server :8000"
Write-Host "  3. cd dashboard && npm run dev                 # Dashboard :3000"
Write-Host "  4. python -m collector.run --source all        # Run all collectors"
