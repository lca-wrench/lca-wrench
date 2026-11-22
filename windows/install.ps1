# Installs LCA Wrench into this folder: its own Python 3.12, Brightway and the app (Windows 10/11).
# Needs internet once, no administrator rights. Nothing outside this folder is changed except one shortcut
# "LCA Wrench" on the desktop (no PATH, no registry, no conda, no Activity Browser, no Brightway projects).
# Started by "Install LCA Wrench.cmd"; written for Windows PowerShell 5.1 (on every Windows 10/11).
# Errors of programs (uv, python) are checked through their exit code: in PowerShell 5.1 'Stop' would also abort on
# their harmless messages on stderr. Cmdlets that must not fail carry -ErrorAction Stop.
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'   # the progress bar of Invoke-WebRequest slows downloads down a lot
$Dir = $PSScriptRoot
$Tools = Join-Path $Dir '.tools'
$Venv = Join-Path $Dir '.venv'
$Log = Join-Path $Dir 'installation-log.txt'
$UvVersion = '0.9.5'
# edition.env (only in other editions, e.g. LCA Wrench Extended): own name, so its shortcut sits next to LCA Wrench's
$Name = 'LCA Wrench'
$EditionFile = Join-Path $Dir 'edition.env'
if (Test-Path $EditionFile) {
    foreach ($line in Get-Content $EditionFile) { if ($line -match '^NAME=(.+)$') { $Name = $Matches[1].Trim() } }
}
# The x64 build on every PC: pyarrow (for BAFU 2026) has no build for Windows on ARM, which runs x64 programs as well.
$UvSha = '515dc53d7553f1357d0abc1f70acd921fbb9e30230b1d9a08737236daa6ee920'
$Python = 'cpython-3.12-windows-x86_64-none'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $Tools 'python'   # Python stays inside this folder
$env:UV_CACHE_DIR = Join-Path $Tools 'cache'
$env:UV_PYTHON_PREFERENCE = 'only-managed'              # never another Python of this PC (conda, python.org, Store)
$env:UV_NO_CONFIG = '1'                                 # ignore uv settings of this user

# Runs only from the release package (pack_windows.sh puts this script next to lca_wrench and the requirements).
# Started from a clone or from "Source code (zip)", nothing fits: stop before anything is written here.
if (-not (Test-Path (Join-Path $Dir 'requirements-lock.txt'))) {
    Write-Host 'ERROR: this folder is not the LCA Wrench installation package (it looks like the source code).' -ForegroundColor Red
    Write-Host 'Download LCA-Wrench-Windows.zip from the release page, unzip it and run "Install LCA Wrench" there:'
    Write-Host '  https://github.com/lca-wrench/lca-wrench/releases/latest'
    Write-Host '"Source code (zip)" on that page is not the installer. To run from source, see "From source" in README.md.'
    exit 1
}

function Fail($text) {
    Write-Host ''
    Write-Host "ERROR: $text" -ForegroundColor Red
    Write-Host "Log: $Log"
    try { Stop-Transcript | Out-Null } catch { }
    exit 1
}

try {
    New-Item -ItemType Directory -Force -Path $Tools -ErrorAction Stop | Out-Null
    $probe = Join-Path $Tools '.write-test'
    Set-Content -Path $probe -Value 'x' -ErrorAction Stop
    Remove-Item $probe -ErrorAction Stop
} catch {
    Write-Host "ERROR: no write access to $Dir" -ForegroundColor Red
    Write-Host 'Move the folder into your user folder (e.g. C:\Users\<name>\LCA-Wrench), not into Program Files.'
    exit 1
}
Start-Transcript -Path $Log -Force | Out-Null

Write-Host "${Name}: installation"
Write-Host "Folder: $Dir"
Write-Host ("Windows {0}, {1}" -f [Environment]::OSVersion.Version, $env:PROCESSOR_ARCHITECTURE)
Write-Host ''

# every file of the package must be here (FILES.txt, written when packing): a partial copy, e.g. over an older
# folder or through OneDrive, otherwise fails only later, when LCA Wrench runs
$FileList = Join-Path $Dir 'FILES.txt'
if (Test-Path $FileList) {
    $Missing = @(Get-Content $FileList | Where-Object { $_ -and -not (Test-Path -LiteralPath (Join-Path $Dir $_)) })
    if ($Missing.Count -gt 0) {
        Write-Host ("Missing in this folder ({0} files), e.g.:" -f $Missing.Count)
        $Missing | Select-Object -First 5 | ForEach-Object { Write-Host "  $_" }
        Fail 'This folder is incomplete. Delete its folder "lca_wrench", unzip the package over it again and run the installation again (README.txt, "Updating"). Or install into a new, empty folder.'
    }
}

try {
    $Uv = Join-Path $Tools 'uv.exe'
    if (-not (Test-Path $Uv)) {
        Write-Host "1/3  Loading the installer tool uv $UvVersion …"
        # The release archive straight from GitHub, checked against a pinned checksum. No install script.
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
        $zip = Join-Path $Tools 'uv.zip'
        $url = "https://github.com/astral-sh/uv/releases/download/$UvVersion/uv-x86_64-pc-windows-msvc.zip"
        $ok = $false
        foreach ($i in 1..3) {
            try { Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing -TimeoutSec 120 -ErrorAction Stop; $ok = $true; break }
            catch { Start-Sleep -Seconds 3 }
        }
        if (-not $ok) { Fail 'Download of uv failed (github.com). Check the internet connection and run it again.' }
        if ((Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower() -ne $UvSha) {
            Remove-Item $zip
            Fail 'uv download corrupted, run it again.'
        }
        Expand-Archive -Path $zip -DestinationPath $Tools -Force -ErrorAction Stop
        Remove-Item $zip
        if (-not (Test-Path $Uv)) { Fail 'uv not found.' }
    }

    Write-Host '2/3  Loading Python 3.12 …'
    & $Uv venv --quiet --allow-existing --python $Python $Venv
    if ($LASTEXITCODE -ne 0) { Fail 'Python 3.12 could not be set up.' }
    $Py = Join-Path $Venv 'Scripts\python.exe'

    Write-Host '3/3  Loading Brightway and the app, this takes a few minutes …'
    # requirements-lock.txt holds the SHA-256 checksum of every package file: uv installs a file only when it matches.
    # A mismatch stops the installation; only versions that do not fit this PC fall back to the newest matching ones
    # (requirements-app.txt, without checksums).
    $Errs = Join-Path $Tools 'lock-errors.txt'
    & $Uv pip install --quiet --require-hashes --python $Py -r (Join-Path $Dir 'requirements-lock.txt') 2> $Errs
    if ($LASTEXITCODE -ne 0) {
        Get-Content $Errs | ForEach-Object { Write-Host "$_" }
        if (Select-String -Path $Errs -Pattern 'hash mismatch' -Quiet) {
            Fail 'A downloaded package does not match its checksum, so it was not installed. Run the installation again later; if it happens again, send installation-log.txt.'
        }
        Write-Host '     The tested versions do not fit this PC, using the newest matching ones (without checksums) …'
        & $Uv pip install --quiet --python $Py -r (Join-Path $Dir 'requirements-app.txt')
        if ($LASTEXITCODE -ne 0) { Fail 'The packages could not be installed. Check the internet connection and run it again.' }
    }
    Remove-Item $Errs -ErrorAction SilentlyContinue
    & $Py -c 'import bw2data, bw2calc, bw2io, fastapi, uvicorn, sentier_brightway, ecoinvent_interface' *> $null
    if ($LASTEXITCODE -ne 0) { Fail 'Installation check failed.' }
    Remove-Item -Recurse -Force (Join-Path $Tools 'cache') -ErrorAction SilentlyContinue   # downloads only, about 300 MB
} catch {
    Fail ("Installation stopped: {0} Check the internet connection and run it again." -f $_.Exception.Message)
}

# a shortcut on the desktop, with the logo, that starts "Start LCA Wrench.cmd" in this folder
try {
    $Desktop = [Environment]::GetFolderPath('Desktop')
    $Shell = New-Object -ComObject WScript.Shell
    $Link = $Shell.CreateShortcut((Join-Path $Desktop "$Name.lnk"))
    $Link.TargetPath = Join-Path $Dir 'Start LCA Wrench.cmd'
    $Link.WorkingDirectory = $Dir
    $Link.IconLocation = (Join-Path $Dir 'lca-wrench.ico') + ',0'
    $Link.Description = "Start $Name"
    $Link.Save()
    Write-Host "A shortcut `"$Name`" is on the desktop."
} catch {
    Write-Host "No desktop shortcut (not allowed here). Start $Name with `"Start LCA Wrench`" in this folder."
}

Write-Host ''
Write-Host "Done. Start $Name with the icon `"$Name`" on the desktop, or `"Start LCA Wrench`" in this folder." -ForegroundColor Green
Stop-Transcript | Out-Null
exit 0
