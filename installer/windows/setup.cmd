@echo off
rem JARVIS Setup: unpacks the app into a temporary folder and runs its installer for this Windows user, with no
rem questions: JARVIS's own Python comes with it, your notes go in Documents\JARVIS Vault, and JARVIS opens at the end.
rem The paths are handed to PowerShell in environment variables, so no folder name can break the command.
setlocal
title JARVIS Setup
echo Installing JARVIS. This takes about a minute, and needs no administrator rights.
echo.
set "JARVIS_ZIP=%~dp0payload.zip"
set "JARVIS_WORK=%TEMP%\JARVIS-Setup-%RANDOM%%RANDOM%"
mkdir "%JARVIS_WORK%" || goto failed
powershell -NoProfile -ExecutionPolicy Bypass -Command "Add-Type -AssemblyName System.IO.Compression.FileSystem; [IO.Compression.ZipFile]::ExtractToDirectory($env:JARVIS_ZIP, $env:JARVIS_WORK)" || goto failed
powershell -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_WORK%\install.ps1" -Friendly
set "CODE=%ERRORLEVEL%"
rmdir /s /q "%JARVIS_WORK%"
echo.
if "%CODE%"=="0" (
  echo All done. This window closes by itself.
  timeout /t 8 >nul
  exit /b 0
)
echo JARVIS Setup did not finish. The message above says why; the full report is in %TEMP%\jarvis-install.log
echo Fix that, then run JARVIS Setup again: it carries on where it stopped, and keeps your settings and chats.
pause
exit /b %CODE%
:failed
echo Could not unpack JARVIS into %JARVIS_WORK%. Make sure there is about 300 MB free on this drive, then run Setup again.
pause
exit /b 1
