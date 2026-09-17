# Build Branch into dist\Branch on a Windows machine.
#
#     powershell -ExecutionPolicy Bypass -File build-windows.ps1
#
# Needs Python 3.10-3.12 on PATH. Everything else it installs into .venv here.
# CI does the same steps in .github/workflows/windows-build.yml; this is for
# building by hand.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv")) {
    Write-Host "Creating .venv..."
    python -m venv .venv
}

Write-Host "Installing dependencies..."
.\.venv\Scripts\python -m pip install --upgrade pip | Out-Null
.\.venv\Scripts\pip install -r requirements-dev.txt

Write-Host "Running tests..."
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python -m unittest discover -s tests
Remove-Item Env:\QT_QPA_PLATFORM

Write-Host "Building..."
.\.venv\Scripts\pyinstaller --clean --noconfirm branch.spec

# A build missing its data does not crash -- it starts, looks right and finds
# nothing. Prove it is complete before calling it done.
Write-Host "Verifying..."
$env:QT_QPA_PLATFORM = "offscreen"
.\dist\Branch\Branch.exe --check
if ($LASTEXITCODE -ne 0) { throw "This build is incomplete -- see above." }
Remove-Item Env:\QT_QPA_PLATFORM

Write-Host ""
# Same reason as the CI workflow: PyInstaller buries bundled files under
# _internal, and START-HERE.txt is meant to be the first thing in the folder.
foreach ($name in @("START-HERE.txt", "README.md", "LICENSE", "NOTICE")) {
    Copy-Item "dist\Branch\_internal\$name" "dist\Branch\" -ErrorAction SilentlyContinue
}

Write-Host "Done. Run it with:  .\dist\Branch\Branch.exe"
Write-Host "Zip dist\Branch\ to hand it to someone."
