# H.A.V.O.C. one-time setup for Windows 11.
# Run from this folder:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
# Installs (via winget, all free): Python 3.12, Node.js LTS, Ollama, Tailscale. Then Python
# packages, the WhatsApp bridge, voice models, the LLM, and runs the setup wizard.

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

Say "Checking Tailscale (private link so your phone can reach Havoc when you're out)"
if (-not (Have tailscale)) {
    $answer = Read-Host "Install Tailscale for phone access? Free for personal use. (Y/n)"
    if ($answer -notmatch '^[nN]') { Winget-Install "Tailscale.Tailscale" }
}

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
& $vpy -m havoc setup

$answer = Read-Host "`nStart Havoc automatically when you log in? (y/N)"
if ($answer -match '^[yY]') {
    $startup = [Environment]::GetFolderPath("Startup")
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut((Join-Path $startup "HAVOC.lnk"))
    $lnk.TargetPath = (Join-Path $PSScriptRoot "start.bat")
    $lnk.WorkingDirectory = $PSScriptRoot
    $lnk.WindowStyle = 7
    $lnk.Save()
    Write-Host "Added to Startup."
}

Write-Host "`nHavoc runs on this PC. If the PC sleeps or shuts down, your phone can't reach it."
$answer = Read-Host "Stop this PC from sleeping while plugged in? (y/N)"
if ($answer -match '^[yY]') {
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    Write-Host "Sleep on AC power disabled (the screen can still turn off)."
}

$desk = [Environment]::GetFolderPath("Desktop")
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut((Join-Path $desk "HAVOC.lnk"))
$lnk.TargetPath = (Join-Path $PSScriptRoot "start.bat")
$lnk.WorkingDirectory = $PSScriptRoot
$lnk.Save()

Say "Done"
Write-Host "1. Sign in to the ambassador dashboard once:  .\.venv\Scripts\python.exe -m havoc login-dashboard"
Write-Host "2. Double-click HAVOC on your desktop (or start.bat)."
Write-Host "3. Scan the WhatsApp QR shown in the HUD the first time."
Write-Host "4. Phone: install Tailscale, sign in with the same account, open the https://...ts.net address"
Write-Host "   the wizard printed, enter your PIN, then 'Add to Home screen'. Or just DM the bot on Discord."
Write-Host "Health check any time:  .\.venv\Scripts\python.exe -m havoc doctor"
