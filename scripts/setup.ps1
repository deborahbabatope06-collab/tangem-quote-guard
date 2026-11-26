# One-step setup for Windows (PowerShell):  .\scripts\setup.ps1   (add -NoMcp to skip Claude Code)
param([switch]$NoMcp)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$Root = (Get-Location).Path

$PyExe = "python"; $PyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) { $PyExe = "py"; $PyArgs = @("-3") }
& $PyExe @PyArgs -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.10+ is required." }

Write-Host "== Creating virtual environment in .venv"
& $PyExe @PyArgs -m venv .venv
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
& $VenvPy -m pip install --quiet --upgrade pip
Write-Host "== Installing"
& $VenvPy -m pip install --quiet --prefer-binary --only-binary=cryptography -e ".[dev]"
if ($LASTEXITCODE -ne 0) { throw "Install failed." }
Write-Host "== Tests"; & $VenvPy -m pytest -q
Write-Host "== Demo";  & $VenvPy -m quote_guard.demo
if ($NoMcp) { exit 0 }

if (Get-Command claude -ErrorAction SilentlyContinue) {
  claude mcp add --scope user --transport http tangem https://mcp.tangem.org/mcp
  claude mcp add --scope user quote-guard -- $VenvPy -m quote_guard.server
  claude mcp list
} else {
  Write-Host "Claude Code not found. Install it, then run:"
  Write-Host "  claude mcp add --scope user --transport http tangem https://mcp.tangem.org/mcp"
  Write-Host "  claude mcp add --scope user quote-guard -- `"$VenvPy`" -m quote_guard.server"
}
