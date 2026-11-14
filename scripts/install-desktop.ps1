# Makes "JARVIS" shortcuts on the Desktop and in the Start menu for a copy of JARVIS run from source (a git clone).
# The packaged installer (installer\windows\install.ps1) does this itself; this script is for people who keep the
# app where they cloned it. It holds no fixed folders: the app is the folder above this script, and the shortcuts go
# through scripts\launch-app.vbs, which finds Python from ".python" beside the app or from PATH each time it starts.
# No administrator rights are needed. Delete the shortcuts to undo.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$launch = Join-Path $PSScriptRoot 'launch-app.vbs'
if (-not (Test-Path -LiteralPath (Join-Path $root 'jcc\__init__.py'))) { throw "No JARVIS app was found in $root." }
$shell = New-Object -ComObject WScript.Shell
foreach ($location in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $link = $shell.CreateShortcut((Join-Path $location 'JARVIS.lnk'))
    $link.TargetPath = Join-Path $env:WINDIR 'System32\wscript.exe'
    $link.Arguments = '"' + $launch + '"'
    $link.WorkingDirectory = $root
    $link.Description = 'JARVIS: your assistant and your notes'
    $link.IconLocation = (Join-Path $env:WINDIR 'System32\shell32.dll') + ',44'
    $link.Save()
    Write-Host ('Made a JARVIS shortcut in ' + $location)
}
