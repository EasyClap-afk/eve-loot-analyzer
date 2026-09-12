param([string]$OutputDirectory = 'dist-v1.5')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
python -m pytest tests -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
python -m PyInstaller --noconfirm --windowed --onedir --distpath $OutputDirectory --name EveLootAnalyzer --add-data 'assets/sde.sqlite3;assets' --add-data 'assets/qt/qtbase_pl.qm;assets/qt' --collect-all keyring --hidden-import keyring.backends.Windows main.py
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
$appDirectory = Join-Path $OutputDirectory 'EveLootAnalyzer'
Copy-Item -LiteralPath 'README.md' -Destination (Join-Path $appDirectory 'README.md') -Force
python scripts/package.py $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw 'ZIP packaging failed' }
