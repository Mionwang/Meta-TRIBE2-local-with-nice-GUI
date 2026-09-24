param([string]$Python = "")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $root ".venv\Scripts\python.exe"
$upstream = Join-Path $root "vendor\tribev2"
$tribeCommit = "af58661791a351a448a489042a28f6c37e1c14b7"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is needed to fetch the official TRIBE v2 source. Install Git for Windows and rerun."
}
New-Item -ItemType Directory -Force -Path (Join-Path $root "INPUT"), (Join-Path $root "OUTPUT"), (Join-Path $root "cache"), (Join-Path $root "vendor") | Out-Null
if (-not (Test-Path -LiteralPath $venvPython)) {
    if (-not $Python) {
        if (Get-Command py -ErrorAction SilentlyContinue) { $Python = "py -3.12" }
        else { throw "Python 3.12 is needed. Install it from python.org, or rerun: .\setup.ps1 -Python 'C:\path\to\python.exe'" }
    }
    if ($Python -eq "py -3.12") { & py -3.12 -m venv (Join-Path $root ".venv") }
    else { & $Python -m venv (Join-Path $root ".venv") }
    if ($LASTEXITCODE -ne 0) { throw "Could not create the Python environment (is Python 3.12 installed?)" }
}
if (-not (Test-Path -LiteralPath $upstream)) {
    git clone https://github.com/facebookresearch/tribev2.git $upstream
    if ($LASTEXITCODE -ne 0) { throw "Could not clone official TRIBE v2" }
    git -C $upstream checkout $tribeCommit
    if ($LASTEXITCODE -ne 0) { throw "Could not check out verified TRIBE v2 commit" }
}
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install --index-url https://download.pytorch.org/whl/cu124 torch==2.6.0 torchvision==0.21.0
if ($LASTEXITCODE -ne 0) { throw "CUDA PyTorch installation failed" }
& $venvPython -m pip install -e $upstream -r (Join-Path $root "requirements-local.txt")
if ($LASTEXITCODE -ne 0) { throw "TRIBE dependency installation failed" }
& $venvPython (Join-Path $root "diagnostics.py")
Write-Host ""
Write-Host "Setup complete. Double-click start_gui.bat to open the app (first analysis downloads ~several GB of model weights)."
