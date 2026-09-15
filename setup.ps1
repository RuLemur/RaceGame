# One-time environment setup.
# Run from the project root: .\setup.ps1
#
# Creates a venv in .venv (if it doesn't exist yet) and installs the
# dependencies from requirements.txt. See README.md ("Zapusk" section)
# for how to run the project afterwards.

$ErrorActionPreference = "Stop"

$venvPython = ".venv\Scripts\python.exe"

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment in .venv ..."
    python -m venv .venv
} else {
    Write-Host ".venv already exists, skipping creation."
}

Write-Host "Upgrading pip ..."
& $venvPython -m pip install --upgrade pip

Write-Host "Installing dependencies from requirements.txt ..."
& $venvPython -m pip install -r requirements.txt

Write-Host ""
Write-Host "Done. To activate the environment in the current PowerShell session:"
Write-Host "    .venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "Or run scripts without activating, directly via the venv's python, e.g.:"
Write-Host "    .venv\Scripts\python.exe -m car_racer.runner.main"
