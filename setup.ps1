# M.A.L.I.C.E. one-time setup for Windows 11.
# Run from this folder:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Installs (via winget, all free): Python 3.12, Node.js LTS, Ollama. Then Python packages,
# the WhatsApp bridge, voice models, the LLM, and runs the setup wizard.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Say($msg) { Write-Host "`n>> $msg" -ForegroundColor Red }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}
function Winget-Install($id) {
    winget install --id $id -e --accept-source-agreements --accept-package-agreements --silent
    Refresh-Path
}

if (-not (Have winget)) {
    Write-Host "winget is missing. Install 'App Installer' from the Microsoft Store, then re-run." -ForegroundColor Yellow
    exit 1
}

Say "Checking Python 3.12"
$py = $null
if (Have py) { try { & py -3.12 --version *> $null; if ($LASTEXITCODE -eq 0) { $py = "py -3.12" } } catch {} }
if (-not $py) { Winget-Install "Python.Python.3.12"; $py = "py -3.12" }

Say "Checking Node.js"
if (-not (Have node)) { Winget-Install "OpenJS.NodeJS.LTS" }

Say "Checking Ollama"
if (-not (Have ollama)) { Winget-Install "Ollama.Ollama" }

Say "Creating the Python environment (.venv)"
if (-not (Test-Path ".venv\Scripts\python.exe")) { Invoke-Expression "$py -m venv .venv" }
$vpy = ".\.venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip
& $vpy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Say "Installing a fallback browser for the dashboard reader (Edge is used first)"
& $vpy -m playwright install chromium

Say "Installing the WhatsApp bridge"
Push-Location whatsapp-bridge
npm install --no-audit --no-fund
Pop-Location

Say "Checking the GPU"
if (Have nvidia-smi) {
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
    Write-Host "RTX 50-series needs a recent NVIDIA driver (R570 or newer, CUDA 12.8+). Update via the NVIDIA app if Whisper falls back to CPU."
} else {
    Write-Host "nvidia-smi not found. Install the latest NVIDIA driver for the RTX 5060." -ForegroundColor Yellow
}

Say "Setup wizard"
& $vpy -m malice setup

$answer = Read-Host "`nStart Malice automatically when you log in? (y/N)"
if ($answer -match '^[yY]') {
    $startup = [Environment]::GetFolderPath("Startup")
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path $startup "MALICE.lnk"))
    $lnk.TargetPath = (Join-Path $PSScriptRoot "start.bat")
    $lnk.WorkingDirectory = $PSScriptRoot
    $lnk.WindowStyle = 7
    $lnk.Save()
    Write-Host "Added to Startup."
}

$desk = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $desk "MALICE.lnk"))
$lnk.TargetPath = (Join-Path $PSScriptRoot "start.bat")
$lnk.WorkingDirectory = $PSScriptRoot
$lnk.Save()

Say "Done"
Write-Host "1. Sign in to the ambassador dashboard once:  .\.venv\Scripts\python.exe -m malice login-dashboard"
Write-Host "2. Double-click MALICE on your desktop (or start.bat)."
Write-Host "3. Scan the WhatsApp QR shown in the HUD the first time."
Write-Host "Health check any time:  .\.venv\Scripts\python.exe -m malice doctor"
