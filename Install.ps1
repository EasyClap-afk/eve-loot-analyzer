# Local-user installation; no administrator permissions required.
$ErrorActionPreference = 'Stop'
$sourceDirectory = Join-Path $PSScriptRoot 'EveLootAnalyzer'
if (-not (Test-Path -LiteralPath (Join-Path $sourceDirectory 'EveLootAnalyzer.exe'))) {
    $sourceDirectory = Join-Path $PSScriptRoot 'dist-v1.5\EveLootAnalyzer'
}
if (-not (Test-Path -LiteralPath (Join-Path $sourceDirectory 'EveLootAnalyzer.exe'))) {
    throw 'EveLootAnalyzer folder missing. Extract the entire ZIP first.'
}
$targetDirectory = Join-Path $env:LOCALAPPDATA 'Programs\EveLootAnalyzer'
New-Item -ItemType Directory -Force -Path $targetDirectory | Out-Null
Copy-Item -Path (Join-Path $sourceDirectory '*') -Destination $targetDirectory -Recurse -Force
$shortcutShell = New-Object -ComObject WScript.Shell
$shortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) 'EVE Loot Analyzer.lnk'
$shortcut = $shortcutShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $targetDirectory 'EveLootAnalyzer.exe'
$shortcut.WorkingDirectory = $targetDirectory
$shortcut.Save()
Write-Host "Installed: $targetDirectory"
Write-Host "Desktop shortcut: $shortcutPath"
