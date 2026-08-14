$ErrorActionPreference = "Stop"

$Ref = if ($env:AGROAI_CLI_REF) { $env:AGROAI_CLI_REF } else { "main" }
$Root = if ($env:AGROAI_CLI_HOME) { $env:AGROAI_CLI_HOME } else { Join-Path $env:LOCALAPPDATA "AGRO-AI\cli" }
$BinDir = if ($env:AGROAI_BIN_DIR) { $env:AGROAI_BIN_DIR } else { Join-Path $env:LOCALAPPDATA "AGRO-AI\bin" }
$Venv = Join-Path $Root "venv"
$Spec = "https://github.com/Lamine-art-png/lamine.github.io/archive/$Ref.zip#subdirectory=sdk/python"

function Fail([string]$Message) {
  Write-Error "agroai installer: $Message"
  exit 1
}

function Resolve-Python {
  if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { return @("py", "-3") }
  }
  if (Get-Command python -ErrorAction SilentlyContinue) {
    & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { return @("python") }
  }
  return $null
}

$Python = Resolve-Python
if (-not $Python) { Fail "Python 3.10 or newer is required" }

Write-Host "Installing AGRO-AI CLI from the official AGRO-AI source ($Ref)..."
New-Item -ItemType Directory -Force -Path $Root, $BinDir | Out-Null

$VenvPython = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
  if ($Python.Count -eq 2) { & $Python[0] $Python[1] -m venv $Venv }
  else { & $Python[0] -m venv $Venv }
  if ($LASTEXITCODE -ne 0) { Fail "could not create the isolated Python environment" }
}

& $VenvPython -m pip install --disable-pip-version-check --upgrade pip | Out-Null
if ($LASTEXITCODE -ne 0) { Fail "could not update pip" }
& $VenvPython -m pip install --disable-pip-version-check --upgrade $Spec
if ($LASTEXITCODE -ne 0) { Fail "could not install the AGRO-AI CLI" }

$VenvCli = Join-Path $Venv "Scripts\agroai.exe"
if (-not (Test-Path $VenvCli)) { Fail "installation completed but agroai.exe was not found" }

$Shim = Join-Path $BinDir "agroai.cmd"
$ShimBody = "@echo off`r`n`"$VenvCli`" %*`r`n"
Set-Content -Path $Shim -Value $ShimBody -Encoding ASCII

$Version = & $VenvCli --version
if ($LASTEXITCODE -ne 0 -or -not $Version) { Fail "the installed agroai executable did not pass its version check" }

$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
$PathEntries = @($UserPath -split ';' | Where-Object { $_ })
if ($PathEntries -notcontains $BinDir) {
  $Updated = if ($UserPath) { "$UserPath;$BinDir" } else { $BinDir }
  [Environment]::SetEnvironmentVariable("Path", $Updated, "User")
  $env:Path = "$env:Path;$BinDir"
  Write-Host "Added $BinDir to your user PATH. New terminals will pick it up automatically."
}

Write-Host "Installed: $Version"
Write-Host "Next: agroai login"
