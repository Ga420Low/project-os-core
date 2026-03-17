@echo off
setlocal
set "ROOT=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%ROOT%tools\start_dev_app.ps1"
