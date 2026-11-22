@echo off
rem H.A.V.O.C. launcher: Ollama + WhatsApp bridge + assistant (HUD opens in an Edge app window).
cd /d "%~dp0"
title H.A.V.O.C.

if not exist ".venv\Scripts\python.exe" (
  echo Run setup.ps1 first:  powershell -ExecutionPolicy Bypass -File .\setup.ps1
  pause
  exit /b 1
)

rem Ollama usually runs as a tray app already; start the server if it isn't up.
tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
if errorlevel 1 (
  tasklist /FI "IMAGENAME eq ollama app.exe" 2>nul | find /I "ollama app.exe" >nul
  if errorlevel 1 start "Ollama" /min ollama serve
)

rem WhatsApp bridge in its own minimised window (shows the QR the first time).
if exist "whatsapp-bridge\node_modules" (
  start "HAVOC WhatsApp bridge" /min cmd /c "cd /d whatsapp-bridge && node index.js"
) else (
  echo WhatsApp bridge not installed; run setup.ps1. Continuing without it.
)

".venv\Scripts\python.exe" -m havoc run %*
if errorlevel 1 pause
