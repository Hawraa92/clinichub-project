# hard.ps1
param(
  [switch]$Fast
)

$ErrorActionPreference = "Stop"

function Step($title, [scriptblock]$block) {
  Write-Host "`n==============================" -ForegroundColor DarkGray
  Write-Host "▶ $title" -ForegroundColor Cyan
  Write-Host "==============================" -ForegroundColor DarkGray
  & $block
}

if (!(Test-Path ".\manage.py")) {
  throw "Run this script from the project root (where manage.py exists)."
}

if (-not $env:VIRTUAL_ENV) {
  Write-Host "⚠️ Warning: VENV not detected. Activate .venv first." -ForegroundColor Yellow
}

Step "Upgrade pip + basic health" {
  python -m pip install -U pip
  python -m pip check
}

Step "Install hard tools" {
  python -m pip install -U ruff bandit pip-audit
  if (-not $Fast) {
    python -m pip install -U mypy django-stubs
  }
}

Step "Lint (ruff)" {
  python -m ruff check .
}

if (-not $Fast) {
  Step "Type check (mypy) - may need config" {
    # If mypy is too strict for now, add: --ignore-missing-imports
    python -m mypy .
  }
}

Step "Security static scan (bandit)" {
  python -m bandit -r . -x ".venv,migrations,static,media,node_modules"
}

Step "Dependency vulnerabilities (pip-audit)" {
  python -m pip_audit
}

Step "Django system checks (deploy)" {
  python manage.py check --deploy
  python manage.py makemigrations --check --dry-run
}

Step "Run full Django tests" {
  python manage.py test -v 2
}

Write-Host "`n✅ HARD SUITE PASSED" -ForegroundColor Green