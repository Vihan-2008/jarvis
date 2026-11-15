<#
.SYNOPSIS
Removes JARVIS: the shortcuts the installer made and the install folder.

.DESCRIPTION
It stops JARVIS if it is running from this folder. Your notes vault and the app's data folder (settings, chats,
history) are kept unless you choose otherwise: run on its own it asks about each, and -DeleteData / -DeleteNotes say
so ahead. Whatever is deleted goes to the Recycle Bin, so it can still be put back. Keys stay in Windows Credential
Manager under "jarvis-command"; remove them there if you want them gone.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File uninstall.ps1
#>
[CmdletBinding()]
param(
    [string]$InstallDir = '',
    [switch]$Quiet,
    [switch]$DeleteData,
    [switch]$DeleteNotes
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

function To-RecycleBin([string]$Folder) {
    Add-Type -AssemblyName Microsoft.VisualBasic
    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($Folder, 'OnlyErrorDialogs', 'SendToRecycleBin')
}

if (-not $Quiet) {
    Write-Host 'This removes the JARVIS app, its shortcuts and its entry in Settings > Apps.'
    Write-Host ''
    $answer = Read-Host "Remove JARVIS from $InstallDir? [y/N]"
    if (-not $answer.Trim().ToLower().StartsWith('y')) { Write-Host 'Nothing was removed.'; Read-Host 'Press Enter to close'; exit 0 }
    Write-Host ''
    Write-Host "JARVIS's data folder holds your settings, chats and history: $data"
    $DeleteData = (Read-Host 'Delete it too? It goes to the Recycle Bin. [y/N]').Trim().ToLower().StartsWith('y')
    if ($vault) {
        Write-Host ''
        Write-Host "Your notes vault holds the notes JARVIS keeps (and any you wrote there): $vault"
        $DeleteNotes = (Read-Host 'Delete your notes too? They go to the Recycle Bin. [y/N]').Trim().ToLower().StartsWith('y')
    }
}

# A JARVIS running from this folder (its own Python is in it) is stopped first.
$prefix = $InstallDir + '\'
foreach ($process in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
    $exe = [string]$process.ExecutablePath
    if ($exe -and $exe.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
        try { Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop } catch { }
    }
}
Start-Sleep -Milliseconds 800

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
Remove-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\JARVIS' -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "Removed the app from $InstallDir."
$kept = @()
if ($DeleteData -and (Test-Path -LiteralPath $data)) { To-RecycleBin $data; Write-Host "Moved JARVIS's data folder to the Recycle Bin: $data" }
elseif (Test-Path -LiteralPath $data) { $kept += "  JARVIS's data folder (settings, chats): $data" }
if ($vault -and $DeleteNotes -and (Test-Path -LiteralPath $vaultFull)) { To-RecycleBin $vaultFull; Write-Host "Moved your notes vault to the Recycle Bin: $vaultFull" }
elseif ($vault) { $kept += "  Your notes vault:      $vault" }
Write-Host ''
if ($kept) { Write-Host 'Kept, for you to keep or delete yourself:'; $kept | ForEach-Object { Write-Host $_ } }
Write-Host '  Keys, if you saved any: Windows Credential Manager, entries starting with "jarvis-command".'
if (-not $Quiet) { Read-Host 'JARVIS is removed. Press Enter to close' | Out-Null }
exit 0
