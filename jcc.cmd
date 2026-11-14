@echo off
rem JARVIS Command Center launcher: jcc ask "...", jcc watch, jcc keys set gemini, ...
set "PYTHONPATH=%~dp0"
set "JCC_PYTHON=python"
if exist "%~dp0.python" for /f "usebackq delims=" %%p in ("%~dp0.python") do set "JCC_PYTHON=%%~dpppython.exe"
"%JCC_PYTHON%" -m jcc %*
