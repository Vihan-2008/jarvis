<#
.SYNOPSIS
Removes JARVIS: the shortcuts the installer made and the install folder.

.DESCRIPTION
It never removes your notes vault or the app's data folder (settings, chats, sessions); it says where they are so
you can keep them, back them up or delete them yourself. Keys stay in Windows Credential Manager under
"jarvis-command"; remove them there if you want them gone.

Close JARVIS before running this.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File uninstall.ps1
#>
[CmdletBinding()]
param(
    [string]$InstallDir = '',
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2

# (Windows PowerShell 5.1 does not fill in $PSScriptRoot inside the parameter block, so the default is set here.)
if (-not $InstallDir) { $InstallDir = Split-Path -Parent $MyInvocation.MyCommand.Path }
$InstallDir = [IO.Path]::GetFullPath($InstallDir).TrimEnd('\')
# Only a folder the installer made is removed: one that holds the app and the installer's own list of its files.
if (-not (Test-Path -LiteralPath (Join-Path $InstallDir 'jcc\__init__.py')) -or
    -not (Test-Path -LiteralPath (Join-Path $InstallDir '.jarvis-files'))) {
    Write-Host "$InstallDir does not look like a folder the JARVIS installer made, so nothing was removed."
    exit 1
}

# Where the notes vault is, read from the settings before they are removed with the app.
$vault = ''
$local = Join-Path $InstallDir 'config\local.toml'
if (Test-Path -LiteralPath $local) {
    $line = Select-String -LiteralPath $local -Pattern "^\s*vault\s*=\s*'([^']*)'" | Select-Object -First 1
    if ($line) { $vault = $line.Matches[0].Groups[1].Value }
}
if ($vault) {
    $expanded = [Environment]::ExpandEnvironmentVariables($vault)
    if ($expanded.StartsWith('~')) { $expanded = $HOME + $expanded.Substring(1) }
    $vaultFull = [IO.Path]::GetFullPath($expanded).TrimEnd('\')
    if ($vaultFull -ieq $InstallDir -or $vaultFull.StartsWith($InstallDir + '\', [StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "Your notes vault ($vaultFull) is inside the install folder. Move it somewhere else first; nothing was removed."
        exit 1
    }
}
$data = Join-Path $env:LOCALAPPDATA 'JarvisCommand'
if ($env:JCC_STATE_DIR) { $data = $env:JCC_STATE_DIR }

if (-not $Quiet) {
    $answer = Read-Host "Remove JARVIS from $InstallDir and its shortcuts? Your notes and data are kept. [y/N]"
    if (-not $answer.Trim().ToLower().StartsWith('y')) { Write-Host 'Nothing was removed.'; exit 0 }
}

$list = Join-Path $InstallDir '.shortcuts'
if (Test-Path -LiteralPath $list) {
    foreach ($link in (Get-Content -LiteralPath $list)) {
        $link = $link.Trim()
        if ($link -and $link.EndsWith('.lnk', [StringComparison]::OrdinalIgnoreCase) -and (Test-Path -LiteralPath $link -PathType Leaf)) {
            Remove-Item -LiteralPath $link -Force
            Write-Host "Removed the shortcut $link"
        }
    }
}

Set-Location -LiteralPath ([IO.Path]::GetTempPath())
Remove-Item -LiteralPath $InstallDir -Recurse -Force
Write-Host "Removed the app from $InstallDir."
Write-Host ''
Write-Host 'Kept, for you to keep or delete yourself:'
if ($vault) { Write-Host "  Your notes vault:      $vault" }
Write-Host "  The app's data folder: $data"
Write-Host '  Keys, if you saved any: Windows Credential Manager, entries starting with "jarvis-command".'
exit 0
