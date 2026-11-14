# Starts JARVIS's background part, hidden, when you sign in to Windows (then open JARVIS any time).
# Adds ONE shortcut to your Startup folder; delete it there to undo. No administrator rights are needed.
# It holds no fixed folders: the app is the folder above this script, and scripts\launch-app.vbs finds Python from
# ".python" beside the app or from PATH each time it starts. (The packaged installer offers the same with -Autostart.)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$launch = Join-Path $PSScriptRoot 'launch-app.vbs'
if (-not (Test-Path -LiteralPath (Join-Path $root 'jcc\__init__.py'))) { throw "No JARVIS app was found in $root." }
$startup = [Environment]::GetFolderPath('Startup')
# An earlier version of this script wrote a .vbs file with fixed folders in it; this shortcut replaces it.
$earlier = Join-Path $startup 'JARVIS Command Watcher.vbs'
if (Test-Path -LiteralPath $earlier) { Remove-Item -LiteralPath $earlier -Force }
$target = Join-Path $startup 'JARVIS Command Watcher.lnk'
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($target)
$link.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
$link.Arguments = '"' + $launch + '" --background'
$link.WorkingDirectory = $root
$link.Description = 'JARVIS background service'
$link.Save()
Write-Host "Installed: $target"
Write-Host 'It starts at your next sign-in. To start it now, double-click that shortcut.'
