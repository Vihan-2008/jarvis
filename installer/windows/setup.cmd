@echo off
rem JARVIS Setup: unpacks the app into a temporary folder and runs its installer for this Windows user.
rem The paths are handed to PowerShell in environment variables, so no folder name can break the command.
setlocal
set "JARVIS_ZIP=%~dp0payload.zip"
set "JARVIS_WORK=%TEMP%\JARVIS-Setup-%RANDOM%%RANDOM%"
mkdir "%JARVIS_WORK%" || goto failed
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath $env:JARVIS_ZIP -DestinationPath $env:JARVIS_WORK -Force" || goto failed
powershell -NoProfile -ExecutionPolicy Bypass -File "%JARVIS_WORK%\install.ps1"
set "CODE=%ERRORLEVEL%"
rmdir /s /q "%JARVIS_WORK%"
echo.
pause
exit /b %CODE%
:failed
echo Could not unpack JARVIS into %JARVIS_WORK%.
pause
exit /b 1
