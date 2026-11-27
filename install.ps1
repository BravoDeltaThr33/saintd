# Install (or upgrade) Saint Directory (saintd) for the current user on Windows.
# Your directory, settings, saved saints and downloaded voices are kept.
# In PowerShell or Command Prompt, in this folder:
#   powershell -ExecutionPolicy Bypass -File install.ps1          installs with pipx when you have it,
#                                                                 otherwise into a private environment
#   powershell -ExecutionPolicy Bypass -File install.ps1 -NoPipx  always installs into the private environment
param([switch]$NoPipx)

Set-Location -LiteralPath $PSScriptRoot

function Stop-Install([string]$Message) {
    Write-Host $Message -ForegroundColor Red
    exit 1
}

# Python 3.10 or newer: python on PATH, then the py launcher (python.org's installer adds it), then python3.
# Without Python, "python" may be only the Microsoft Store's placeholder, which fails the check.
function Find-Python {
    $check = 'import sys; print(sys.executable); sys.exit(0 if sys.version_info >= (3, 10) else 1)'
    foreach ($exe in 'python', 'py', 'python3') {
        if (-not (Get-Command $exe -CommandType Application -ErrorAction SilentlyContinue)) { continue }
        $pyArgs = @()
        if ($exe -eq 'py') { $pyArgs = @('-3') }
        $out = & $exe @pyArgs -c $check 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return ([string]($out | Select-Object -Last 1)).Trim() }
    }
    return $null
}

function Test-OnPath([string]$Dir) {
    $want = $Dir.TrimEnd('\')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    foreach ($p in (($env:Path + ';' + $user) -split ';')) {
        if ($p -and ([Environment]::ExpandEnvironmentVariables($p).TrimEnd('\') -ieq $want)) { return $true }
    }
    return $false
}

# Add a folder to the user's PATH, keeping the value's type and its %VARIABLES%, and tell Windows
# that the environment changed (new terminals then find saintd).
function Add-ToUserPath([string]$Dir) {
    $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
    try {
        $raw = [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
        $value = $Dir
        if ($raw) { $value = $raw.TrimEnd(';') + ';' + $Dir }
        $key.SetValue('Path', $value, [Microsoft.Win32.RegistryValueKind]::ExpandString)
    } finally {
        $key.Close()
    }
    try {
        if (-not ('SaintD.Env' -as [type])) {
            Add-Type -Namespace SaintD -Name Env -MemberDefinition @'
[DllImport("user32.dll", CharSet = CharSet.Unicode)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint msg, UIntPtr wParam, string lParam,
                                               uint flags, uint timeout, out UIntPtr result);
'@
        }
        $result = [UIntPtr]::Zero
        [void][SaintD.Env]::SendMessageTimeout([IntPtr]0xffff, 0x1a, [UIntPtr]::Zero, 'Environment', 2, 5000,
                                               [ref]$result)
    } catch {
        # new terminals pick the change up after the next sign-in
    }
}

# pip builds saintd inside this folder and leaves build\ behind. An old build\ would carry files that
# have since been removed from saintd into the new install, so start from a clean folder and tidy up after.
function Clear-Build {
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue -Path 'build', 'saint_directory.egg-info'
}

$py = Find-Python
if (-not $py) {
    Stop-Install ("Saint Directory needs Python 3.10 or newer. Install it with`n" +
                  "    winget install Python.Python.3.13`n" +
                  "(or from https://www.python.org/downloads/), then open a new terminal and run this again.")
}
if (Get-Process -Name saintd -ErrorAction SilentlyContinue) {
    Stop-Install 'Saint Directory is running. Quit it (Ctrl+Q) and run this again.'
}

$venv = Join-Path $HOME '.local\share\saintd-venv'
$localBin = Join-Path $HOME '.local\bin'
$piperNote = "Natural voices (Piper) could not be installed now; reading aloud uses the voices of Windows.`n" +
             "You can add Piper later in Settings -> Voice & Reading aloud (Install Piper)."
$pipx = $null
if (-not $NoPipx) { $pipx = Get-Command pipx -CommandType Application -ErrorAction SilentlyContinue }

Clear-Build
try {
    if ($pipx) {
        Write-Host 'Installing with pipx...'
        & pipx install --force --python $py .
        if ($LASTEXITCODE -ne 0) { Stop-Install 'pipx could not install Saint Directory (see above).' }
        Write-Host 'Adding Piper for natural reading voices (about 60 MB)...'
        & pipx inject --force saint-directory piper-tts *> $null
        if ($LASTEXITCODE -ne 0) { Write-Host $piperNote }
        $binDir = $localBin
        $pipxBin = [Environment]::GetEnvironmentVariable('PIPX_BIN_DIR')
        if ($pipxBin) { $binDir = $pipxBin }
        # A copy installed earlier without pipx is no longer used: remove it.
        if (Test-Path -LiteralPath (Join-Path $venv 'pyvenv.cfg')) {
            if ($binDir.TrimEnd('\') -ine $localBin) {
                Remove-Item -Force -ErrorAction SilentlyContinue -LiteralPath (Join-Path $localBin 'saintd.exe')
            }
            Remove-Item -Recurse -Force -LiteralPath $venv
            Write-Host "Removed the earlier copy in $venv (saintd is now installed with pipx)."
        }
    } else {
        Write-Host "Installing into $venv"
        & $py -m venv $venv
        if ($LASTEXITCODE -ne 0) { Stop-Install "Could not create a virtual environment in $venv." }
        $vpy = Join-Path $venv 'Scripts\python.exe'
        & $vpy -m pip install --quiet --disable-pip-version-check --upgrade pip
        & $vpy -m pip install --quiet --disable-pip-version-check .
        if ($LASTEXITCODE -ne 0) { Stop-Install 'pip could not install Saint Directory (see above).' }
        Write-Host 'Adding Piper for natural reading voices (about 60 MB)...'
        & $vpy -m pip install --quiet --disable-pip-version-check piper-tts *> $null
        if ($LASTEXITCODE -ne 0) { Write-Host $piperNote }
        $binDir = $localBin
        New-Item -ItemType Directory -Force -Path $binDir | Out-Null
        # The launcher pip made knows where its Python is, so a copy of it works from any folder.
        Copy-Item -Force -LiteralPath (Join-Path $venv 'Scripts\saintd.exe') -Destination (Join-Path $binDir 'saintd.exe')
    }
} finally {
    Clear-Build
}

$start = 'saintd'
if (-not (Test-OnPath $binDir)) {
    try {
        Add-ToUserPath $binDir
        Write-Host "Added $binDir to your PATH. Open a new terminal to start saintd by name."
    } catch {
        Write-Host ("Note: $binDir is not on your PATH. To start saintd by name, add it to Path in" +
                    " Settings -> System -> About -> Advanced system settings -> Environment Variables.")
    }
    $start = Join-Path $binDir 'saintd.exe'
}

Write-Host ''
Write-Host "Saint Directory is installed. Start it with:  $start"
Write-Host 'It looks best in Windows Terminal.'
Write-Host 'Press P on a saint to hear the life read aloud (Settings -> Voice & Reading aloud to choose a voice).'
