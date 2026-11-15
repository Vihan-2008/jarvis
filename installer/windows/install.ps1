<#
.SYNOPSIS
Installs JARVIS for the current Windows user. No administrator rights are needed.

.DESCRIPTION
What it does, in order:
  1. Finds Python 3.11 or newer (py -3, then python). If there is none it says so and, unless -Quiet, offers to
     install Python 3.12 with winget. It never downloads an installer by itself.
  2. Copies the app's files into -InstallDir. Run again over an existing install, it upgrades it: config\local.toml
     and every other file the installer did not put there are kept.
  3. Writes ".python" in the install folder: one line, the full path of pythonw.exe.
  4. Runs "python -m jcc.firstrun" to set up the notes vault (an Obsidian vault) and remember where it is.
  5. Makes "JARVIS" shortcuts (Desktop and Start menu, or -ShortcutDir) that start pythonw.exe -m jcc.desktop.
  6. Optionally installs Obsidian (winget, or opens its download page) and starts JARVIS at sign-in (-Autostart).
  7. Writes uninstall.ps1 into the install folder.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File install.ps1 -Quiet -Vault "D:\Notes\JARVIS"
#>
[CmdletBinding()]
param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\JARVIS'),
    [string]$Vault = '',
    [string]$ShortcutDir = '',
    [switch]$NoShortcuts,
    [switch]$InstallObsidian,
    [switch]$NoObsidian,
    [switch]$Autostart,
    [switch]$Quiet,
    [string]$Source = '',
    [string]$Python = '',
    [switch]$Friendly
)
# -Friendly is how JARVIS-Setup.exe runs it: no questions (notes in Documents\JARVIS Vault, no Obsidian), JARVIS
# listed in Settings > Apps so it can be removed from there, a running JARVIS restarted, and JARVIS opened at the end.
if ($Friendly) {
    $Quiet = $true; $NoObsidian = $true; $Autostart = $true          # (it starts in the background at sign-in, for "Hey JARVIS")
    try { Start-Transcript -Path (Join-Path $env:TEMP 'jarvis-install.log') -Force | Out-Null } catch { }
}

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2

function Find-Installed {
    # The JARVIS this installer made before, wherever it is: the one Settings > Apps lists, else the one answering on its
    # port, else the one a JARVIS shortcut starts. Only a folder the installer made (its list of files is there) counts:
    # a developer's own copy is never written over.
    $made = { param($folder) $folder -and (Test-Path -LiteralPath (Join-Path $folder 'jcc\__init__.py')) -and (Test-Path -LiteralPath (Join-Path $folder '.jarvis-files')) }
    $key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\JARVIS'
    if (Test-Path $key) {
        $entry = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
        if ($entry -and ($entry.PSObject.Properties.Name -contains 'InstallLocation') -and (& $made ([string]$entry.InstallLocation))) { return [string]$entry.InstallLocation }
    }
    try {
        foreach ($owner in @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction Stop | ForEach-Object { $_.OwningProcess })) {
            $exe = [string](Get-CimInstance Win32_Process -Filter "ProcessId=$owner" -ErrorAction SilentlyContinue).ExecutablePath
            $folder = $exe
            for ($i = 0; $i -lt 5 -and $folder; $i++) {
                $folder = Split-Path -Parent $folder
                if (& $made $folder) { return $folder }
            }
        }
    } catch { }
    try {
        $shell = New-Object -ComObject WScript.Shell
        foreach ($place in @([Environment]::GetFolderPath('Programs'), [Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Startup'))) {
            foreach ($link in @(Get-ChildItem -LiteralPath $place -Filter 'JARVIS*.lnk' -ErrorAction SilentlyContinue)) {
                $folder = [string]$shell.CreateShortcut($link.FullName).WorkingDirectory
                if (& $made $folder) { return $folder }
            }
        }
    } catch { }
    return ''
}

if ($Friendly -and -not $PSBoundParameters.ContainsKey('InstallDir')) {
    # Running Setup again updates the JARVIS that is there; it never installs a second one.
    $there = Find-Installed
    if ($there) { $InstallDir = $there }
}

# Files and folders that are never copied into the install folder: the person's own settings, the build and test
# material, and the owner's own deployment tool. Paths are relative to the source folder, with backslashes.
$NeverCopied = @('runtime', '.git', '.github', '.claude', 'tests', 'installer', 'website', 'dist', 'LEDGER.md',
                 'scripts\deploy.py', 'config\local.toml', '.python', '.jarvis-files', '.shortcuts',
                 'install.ps1', 'uninstall.ps1', 'setup.cmd', 'jarvis.ico')

function Say([string]$Text) { Write-Host $Text }

function Ask-YesNo([string]$Question, [bool]$Default) {
    if ($Quiet) { return $Default }
    $hint = if ($Default) { '[Y/n]' } else { '[y/N]' }
    $answer = Read-Host "$Question $hint"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim().ToLower().StartsWith('y')
}

function Find-Source {
    # The app's files sit beside this script in the downloaded package. Run from a copy of the repository, the
    # script is in installer\windows and the app is two folders up.
    if ($Source) { return (Resolve-Path -LiteralPath $Source).Path }
    foreach ($candidate in @($PSScriptRoot, (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)))) {
        if ($candidate -and (Test-Path -LiteralPath (Join-Path $candidate 'jcc\__init__.py'))) { return $candidate }
    }
    throw 'Could not find the JARVIS app files (a "jcc" folder) beside this script. Use -Source to say where they are.'
}

function Test-Python([string[]]$Command) {
    # Returns the full path of python.exe when the command is Python 3.11 or newer, otherwise $null. The Microsoft
    # Store's "python" placeholder only prints a message, so anything that does not answer exactly is skipped.
    try {
        $exe = $Command[0]
        $rest = @()
        if ($Command.Count -gt 1) { $rest = $Command[1..($Command.Count - 1)] }
        $out = & $exe @rest -c 'import sys; print(sys.version_info >= (3, 11)); print(sys.executable)' 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return $null }
        $lines = @($out)
        if ($lines.Count -ge 2 -and $lines[0].Trim() -eq 'True' -and (Test-Path -LiteralPath $lines[1].Trim())) {
            return $lines[1].Trim()
        }
    } catch { }
    return $null
}

function Find-Python {
    if ($Python) {
        $found = Test-Python @($Python)
        if (-not $found) { throw "The Python given with -Python ($Python) is not Python 3.11 or newer." }
        return $found
    }
    foreach ($command in @(@('py', '-3'), @('python'), @('python3'))) {
        if (Get-Command $command[0] -ErrorAction SilentlyContinue) {
            $found = Test-Python $command
            if ($found) { return $found }
        }
    }
    return $null
}

function Refresh-Path {
    # A program winget has just installed is on the PATH saved for new windows, not yet on this one's.
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machine;$user"
}

function Get-RelativeFiles([string]$Root) {
    $rootFull = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
    Get-ChildItem -LiteralPath $rootFull -Recurse -File -Force | ForEach-Object {
        $_.FullName.Substring($rootFull.Length + 1)
    } | Where-Object {
        $relative = $_
        $parts = $relative.Split('\')
        $skip = $parts -contains '__pycache__' -or $relative.EndsWith('.pyc')
        foreach ($never in $NeverCopied) {
            if ($relative -ieq $never -or $relative.StartsWith($never + '\', [StringComparison]::OrdinalIgnoreCase)) { $skip = $true }
        }
        -not $skip
    }
}

function Write-TextFile([string]$Path, [string]$Text) {
    # No byte-order mark: launch-app.vbs and jcc.cmd read these files as plain text.
    [IO.File]::WriteAllText($Path, $Text, (New-Object Text.UTF8Encoding($false)))
}

function New-Shortcut([string]$Path, [string]$Target, [string]$Arguments, [string]$WorkDir, [string]$Icon) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $Target
    $link.Arguments = $Arguments
    $link.WorkingDirectory = $WorkDir
    $link.Description = 'JARVIS: your assistant and your notes'
    if ($Icon -and (Test-Path -LiteralPath $Icon)) { $link.IconLocation = "$Icon,0" }
    $link.Save()
}

function Assert-Space([string]$Folder, [int]$NeedMB) {
    # Enough room on the drive for the app (and its own Python), or a plain message saying how much is missing.
    $root = [IO.Path]::GetPathRoot([IO.Path]::GetFullPath($Folder))
    try { $free = (New-Object IO.DriveInfo $root).AvailableFreeSpace } catch { return }
    if ($free -lt [int64]$NeedMB * 1MB) {
        throw ("JARVIS needs about $NeedMB MB free on $root, and there is only {0} MB. Free some space (for example, empty the Recycle Bin), then run Setup again." -f [math]::Round($free / 1MB))
    }
}

function Stop-RunningJarvis([string]$Folder) {
    # A JARVIS running from this folder is stopped before its files are replaced (and opened again at the end).
    # With -Friendly (a person upgrading the JARVIS they use), the one answering on its usual port is stopped too.
    $stopped = $false
    $prefix = $Folder.TrimEnd('\') + '\'
    $owners = @()
    if ($Friendly) {
        try { $owners = @(Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction Stop | ForEach-Object { $_.OwningProcess }) } catch { }
    }
    $all = @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)
    # The processes that started this installer (JARVIS's update helper, which runs on JARVIS's own Python in this
    # folder) are never stopped: the update would be cut off half-way.
    $spared = @{}
    $id = $PID
    for ($i = 0; $i -lt 16 -and $id; $i++) {
        $spared[[int]$id] = $true
        $parent = $all | Where-Object { $_.ProcessId -eq $id } | Select-Object -First 1
        $id = if ($parent) { [int]$parent.ParentProcessId } else { 0 }
    }
    foreach ($process in $all) {
        if ($spared.ContainsKey([int]$process.ProcessId)) { continue }
        $exe = [string]$process.ExecutablePath
        $mine = $exe -and $exe.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)
        $ours = ($owners -contains $process.ProcessId) -and ([string]$process.CommandLine -match 'jcc')
        if ($mine -or $ours) {
            try { Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop; $stopped = $true } catch { }
        }
    }
    if ($stopped) { Start-Sleep -Seconds 2 }
    return $stopped
}

function Install-Runtime([string]$From, [string]$To) {
    # JARVIS's own Python: unpacked only when it is new or another version, beside the old one, then swapped in, so a
    # JARVIS (or an update) still running on the old one is never broken half-way. Old copies are removed when free.
    $zip = Join-Path $From 'runtime\python.zip'
    $want = (Get-Content -LiteralPath (Join-Path $From 'runtime\VERSION') -ErrorAction SilentlyContinue | Select-Object -First 1)
    $home_ = Join-Path $To 'runtime'
    $target = Join-Path $home_ 'python'
    $marker = Join-Path $target '.jarvis-runtime'
    $have = if (Test-Path -LiteralPath $marker) { (Get-Content -LiteralPath $marker | Select-Object -First 1) } else { '' }
    if ($have -and $have -eq $want -and (Test-Path -LiteralPath (Join-Path $target 'pythonw.exe'))) {
        Say "JARVIS's own Python ($want) is already in place."
    } else {
        Say "Unpacking JARVIS's own Python ($want); nothing else needs to be installed..."
        New-Item -ItemType Directory -Force -Path $home_ | Out-Null
        $fresh = Join-Path $home_ 'python.new'
        if (Test-Path -LiteralPath $fresh) { Remove-Item -LiteralPath $fresh -Recurse -Force }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($zip, $fresh)
        Write-TextFile (Join-Path $fresh '.jarvis-runtime') ($want + "`r`n")
        $moved = $true
        if (Test-Path -LiteralPath $target) {
            try { Rename-Item -LiteralPath $target -NewName ('python.old-' + [DateTime]::Now.Ticks) -ErrorAction Stop }
            catch { $moved = $false }
        }
        if ($moved) { Rename-Item -LiteralPath $fresh -NewName 'python' }
        else {
            # (In use: an update's helper runs on it. The one in place still works; the new one goes in next time.)
            Remove-Item -LiteralPath $fresh -Recurse -Force -ErrorAction SilentlyContinue
            Say "JARVIS's own Python is in use, so the one in place is kept for now."
        }
    }
    foreach ($old in @(Get-ChildItem -LiteralPath $home_ -Directory -Filter 'python.old-*' -ErrorAction SilentlyContinue)) {
        try { Remove-Item -LiteralPath $old.FullName -Recurse -Force -ErrorAction Stop } catch { }
    }
    return (Join-Path $target 'python.exe')
}

# ------------------------------------------------------------------------------------------------------- Python
Say 'Installing JARVIS for this Windows user (no administrator rights needed).'
$sourceDir = Find-Source
$bundled = (-not $Python) -and (Test-Path -LiteralPath (Join-Path $sourceDir 'runtime\python.zip'))
$pythonExe = if ($bundled) { 'bundled' } else { Find-Python }
if (-not $pythonExe) {
    Say 'JARVIS needs Python 3.11 or newer, and none was found on this PC.'
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget -and -not $Quiet -and (Ask-YesNo 'Install Python 3.12 now with winget (Windows'' own package manager)?' $true)) {
        & winget install --id Python.Python.3.12 -e --source winget
        Refresh-Path
        $pythonExe = Find-Python
    }
    if (-not $pythonExe) {
        Say 'Please install Python 3.11 or newer from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),'
        Say 'or run:  winget install --id Python.Python.3.12 -e'
        Say 'Then run this installer again.'
        exit 1
    }
}
# ---------------------------------------------------------------------------------------------------- the files
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
Assert-Space $InstallDir ($(if ($bundled) { 250 } else { 60 }))
$restart = Stop-RunningJarvis $InstallDir
$upgrade = Test-Path -LiteralPath (Join-Path $InstallDir 'jcc\__init__.py')
if ((Test-Path -LiteralPath $InstallDir) -and -not $upgrade -and (Get-ChildItem -LiteralPath $InstallDir -Force | Select-Object -First 1)) {
    throw "The folder $InstallDir already has other files in it and is not a JARVIS install. Choose an empty folder with -InstallDir."
}
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
$sameFolder = ([IO.Path]::GetFullPath($sourceDir).TrimEnd('\')) -ieq $InstallDir.TrimEnd('\')
$manifestPath = Join-Path $InstallDir '.jarvis-files'
$shipped = @(Get-RelativeFiles $sourceDir)
if (-not $sameFolder) {
    foreach ($relative in $shipped) {
        $target = Join-Path $InstallDir $relative
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath (Join-Path $sourceDir $relative) -Destination $target -Force
    }
    # A file an earlier version shipped and this one does not would otherwise linger and could still be imported.
    # Only files named in the earlier list are removed: anything the person added is never touched.
    if (Test-Path -LiteralPath $manifestPath) {
        $now = @{}
        foreach ($relative in $shipped) { $now[$relative.ToLower()] = $true }
        foreach ($old in (Get-Content -LiteralPath $manifestPath)) {
            $old = $old.Trim()
            if (-not $old -or $now.ContainsKey($old.ToLower()) -or $old.Contains('..') -or [IO.Path]::IsPathRooted($old)) { continue }
            $stale = Join-Path $InstallDir $old
            if (Test-Path -LiteralPath $stale -PathType Leaf) { Remove-Item -LiteralPath $stale -Force }
        }
    }
    Write-TextFile $manifestPath (($shipped -join "`r`n") + "`r`n")
    $uninstaller = @((Join-Path $PSScriptRoot 'uninstall.ps1'), (Join-Path $sourceDir 'installer\windows\uninstall.ps1')) |
        Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $uninstaller) { throw 'uninstall.ps1 is missing from the installer package.' }
    Copy-Item -LiteralPath $uninstaller -Destination (Join-Path $InstallDir 'uninstall.ps1') -Force
}
if ($upgrade) { Say "Upgraded the app in $InstallDir (your settings, chats and your own files were kept)." }
else { Say "Copied the app to $InstallDir." }
if ($bundled) { $pythonExe = Install-Runtime $sourceDir $InstallDir }
$pythonw = Join-Path (Split-Path -Parent $pythonExe) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw)) { $pythonw = $pythonExe }
Say "Using Python: $pythonExe"
Write-TextFile (Join-Path $InstallDir '.python') ($pythonw + "`r`n")

# --------------------------------------------------------------------------------------------------- the vault
$local = Join-Path $InstallDir 'config\local.toml'
$hasVault = (Test-Path -LiteralPath $local) -and (Select-String -LiteralPath $local -Pattern '^\s*vault\s*=' -Quiet)
$firstrun = @('-m', 'jcc.firstrun', '--app-dir', $InstallDir, '--yes')
if ($Vault) {
    $firstrun += @('--vault', $Vault)
} elseif (-not $hasVault -and $Friendly) {
    $firstrun += @('--vault', (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'JARVIS Vault'))
} elseif (-not $hasVault -and -not $Quiet) {
    $offered = Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'JARVIS Vault'
    Say ''
    Say 'JARVIS keeps its memory as plain notes in a folder you own (an Obsidian vault).'
    $answer = Read-Host "Where should your notes be kept? Press Enter for $offered"
    $answer = $answer.Trim().Trim('"')
    if (-not $answer) { $answer = $offered }
    $firstrun += @('--vault', $answer)
}
if ($Quiet) { $firstrun += '--no-open' }
Push-Location -LiteralPath $InstallDir
try {
    & $pythonExe @firstrun
    if ($LASTEXITCODE -ne 0) { throw 'Setting up the notes vault did not finish (see the message above).' }
} finally { Pop-Location }

# ------------------------------------------------------------------------------------------- icon and shortcuts
$icon = Join-Path $InstallDir 'jarvis.ico'
Push-Location -LiteralPath $InstallDir
try {
    # (No quotes inside the Python code: Windows PowerShell 5.1 drops inner double quotes when it starts a program.)
    & $pythonExe -c 'import sys, pathlib; from jcc.tray import icon_bytes; pathlib.Path(sys.argv[1]).write_bytes(icon_bytes(48))' $icon 2>$null
    if ($LASTEXITCODE -ne 0) { $icon = '' }
} catch { $icon = '' } finally { Pop-Location }

$made = @()
if (-not $NoShortcuts) {
    $places = if ($ShortcutDir) { @($ShortcutDir) } else { @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs')) }
    foreach ($place in $places) {
        New-Item -ItemType Directory -Force -Path $place | Out-Null
        $link = Join-Path $place 'JARVIS.lnk'
        New-Shortcut $link $pythonw '-m jcc.desktop' $InstallDir $icon
        $made += $link
        Say "Made a JARVIS shortcut in $place"
    }
}
if ($Autostart) {
    $startup = if ($ShortcutDir) { $ShortcutDir } else { [Environment]::GetFolderPath('Startup') }
    $link = Join-Path $startup 'JARVIS (background).lnk'
    New-Shortcut $link $pythonw '-m jcc.desktop --background' $InstallDir $icon
    $made += $link
    Say 'JARVIS will start in the background when you sign in to Windows.'
}
# The uninstaller removes exactly these shortcuts. Earlier ones are kept in the list until it runs.
$shortcutList = Join-Path $InstallDir '.shortcuts'
$known = @()
if (Test-Path -LiteralPath $shortcutList) { $known = @(Get-Content -LiteralPath $shortcutList | Where-Object { $_.Trim() }) }
$all = @($known + $made | Select-Object -Unique)
Write-TextFile $shortcutList (($all -join "`r`n") + "`r`n")

# ------------------------------------------------------------------------------------------------------ Obsidian
$wantObsidian = $false
if ($InstallObsidian) { $wantObsidian = $true }
elseif (-not $NoObsidian -and -not $Quiet) {
    $wantObsidian = Ask-YesNo 'Install Obsidian (a free app to read and edit your notes)?' $true
}
if ($wantObsidian) {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        & winget install --id Obsidian.Obsidian -e --source winget
    } else {
        Say 'winget is not available here, so the Obsidian download page is opening instead.'
        Start-Process 'https://obsidian.md/download'
    }
}

# ------------------------------------------------------------------------------------- Settings > Apps, and go
$key = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\JARVIS'
$listed = $false
if (Test-Path $key) {
    $entry = Get-ItemProperty -Path $key -ErrorAction SilentlyContinue
    if ($entry -and ($entry.PSObject.Properties.Name -contains 'InstallLocation')) { $listed = ([string]$entry.InstallLocation -eq $InstallDir) }
}
if ($Friendly -or $listed) {
    # Listed in Settings > Apps (for this user only, no administrator rights), so it can be removed from there. An update
    # of a copy listed there (JARVIS's own update helper) brings its version up to date.
    $version = (Get-Content -LiteralPath (Join-Path $InstallDir 'VERSION') -ErrorAction SilentlyContinue | Select-Object -First 1)
    New-Item -Path $key -Force | Out-Null
    $values = @{ DisplayName = 'JARVIS'; DisplayVersion = [string]$version; Publisher = 'JARVIS (open source)'; InstallLocation = $InstallDir
                 DisplayIcon = $icon; NoModify = 1; NoRepair = 1
                 UninstallString = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $InstallDir 'uninstall.ps1')`"" }
    foreach ($name in $values.Keys) {
        $kind = if ($values[$name] -is [int]) { 'DWord' } else { 'String' }
        New-ItemProperty -Path $key -Name $name -Value $values[$name] -PropertyType $kind -Force | Out-Null
    }
}

Say ''
Say 'JARVIS is installed.'
Say "  App:          $InstallDir"
Say "  Uninstaller:  Settings > Apps > JARVIS (or $(Join-Path $InstallDir 'uninstall.ps1'))"
if ($Friendly) {
    Say ''
    Say 'Opening JARVIS now. Next time, open it from the JARVIS icon on your desktop or in the Start menu.'
    Start-Process -FilePath $pythonw -ArgumentList '-m', 'jcc.desktop' -WorkingDirectory $InstallDir
} else {
    Say '  Start it from the JARVIS shortcut, or run:'
    Say "    `"$pythonw`" -m jcc.desktop   (in $InstallDir)"
}
if ($Friendly) { try { Stop-Transcript | Out-Null } catch { } }      # (the report ends cleanly)
exit 0
