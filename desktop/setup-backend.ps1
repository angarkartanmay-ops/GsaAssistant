# First-run setup for the HAVOC desktop app (run by the app; safe to re-run).
# Installs, all free: Python 3.12, Ollama, Tailscale (via winget), then HAVOC's Python packages
# into <HavocHome>\venv, the voice models and the qwen3:8b model.
param(
    [Parameter(Mandatory = $true)][string]$HavocHome,
    [Parameter(Mandatory = $true)][string]$Backend,
    [string]$Model = "qwen3:8b"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$env:HAVOC_HOME = $HavocHome
$env:PYTHONUTF8 = "1"

function Step($m) { Write-Output ">> $m" }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Winget($id) {
    if (-not (Have winget)) { throw "winget is missing. Install 'App Installer' from the Microsoft Store, then press Retry." }
    winget install --id $id -e --silent --accept-source-agreements --accept-package-agreements | Out-String | Write-Output
    Refresh-Path
}

try {
    New-Item -ItemType Directory -Force -Path $HavocHome | Out-Null

    Step "Python 3.12"
    $py = $null
    if (Have py) { & py -3.12 --version *> $null; if ($LASTEXITCODE -eq 0) { $py = "py" } }
    if (-not $py) { Winget "Python.Python.3.12"; $py = "py" }

    $venv = Join-Path $HavocHome "venv"
    $vpy = Join-Path $venv "Scripts\python.exe"
    if (-not (Test-Path $vpy)) {
        Step "Creating HAVOC's Python environment"
        & $py -3.12 -m venv $venv
        if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment." }
    }

    Step "Installing HAVOC's packages (a few minutes)"
    & $vpy -m pip install --upgrade pip --quiet
    & $vpy -m pip install -r (Join-Path $Backend "requirements.txt") --quiet --disable-pip-version-check
    if ($LASTEXITCODE -ne 0) { throw "pip install failed." }

    Step "Browser for reading the dashboard"
    & $vpy -m playwright install chromium | Out-Null

    Step "Voice models"
    Push-Location $Backend
    & $vpy -m havoc models
    Pop-Location
    if ($LASTEXITCODE -ne 0) { throw "Voice model download failed." }

    Step "Ollama (runs the AI model on your RTX 5060)"
    if (-not (Have ollama)) { Winget "Ollama.Ollama" }
    try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:11434/api/version -TimeoutSec 3 | Out-Null }
    catch { Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden; Start-Sleep -Seconds 4 }

    Step "Downloading the AI model $Model (about 5 GB, once)"
    & ollama pull $Model
    if ($LASTEXITCODE -ne 0) { throw "ollama pull $Model failed. Check your internet connection." }

    Step "Tailscale (lets your phone reach HAVOC privately)"
    if (-not (Have tailscale)) {
        try { Winget "Tailscale.Tailscale" } catch { Write-Output "! Tailscale didn't install ($_). Phone access via Discord DM still works." }
    }
    Write-Output "Tailscale installed. Sign in from its tray icon when you set up the phone."

    Step "All set"
    exit 0
}
catch {
    Write-Output "! $($_.Exception.Message)"
    exit 1
}
