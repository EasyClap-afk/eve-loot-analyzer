param([string]$Installer = 'dist-v1.6\EveLootAnalyzer-Setup-1.6.exe')
$ErrorActionPreference = 'Stop'
$workspacePath = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
Set-Location -LiteralPath $workspacePath
$targetPath = [IO.Path]::GetFullPath((Join-Path $workspacePath 'build\installer-smoke'))
if (-not $targetPath.StartsWith($workspacePath + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe test target.' }
$registryPath = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{E1C9CF31-22A2-45B4-8EB4-606DA3C70821}_is1'
if (Test-Path $registryPath) { throw 'An installed copy already exists. Run this test in a separate Windows account.' }
if (Test-Path -LiteralPath $targetPath) { throw 'Smoke-test directory already exists. Choose a clean test environment.' }
$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$testDataPath = Join-Path $workspacePath 'build\installer-userdata'
New-Item -ItemType Directory -Force -Path $testDataPath | Out-Null
$sentinelPath = Join-Path $testDataPath 'preserve.txt'
'preserve user data' | Set-Content -LiteralPath $sentinelPath
foreach ($wizardLanguage in @('english','polish')) {
    $setupProcess = Start-Process -FilePath $installerPath -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/NOICONS','/TASKS="!desktopicon"',"/LANG=$wizardLanguage",('/DIR="' + $targetPath + '"')) -WindowStyle Hidden -Wait -PassThru
    if ($setupProcess.ExitCode -ne 0) { throw "Installer failed: $($setupProcess.ExitCode)" }
    if (-not (Test-Path -LiteralPath (Join-Path $targetPath '_internal\assets\qt\qtbase_pl.qm'))) { throw 'Bundled resources missing.' }
    Write-Output "Install/upgrade passed: $wizardLanguage"
}
$previousDataPath = $env:EVE_LOOT_DATA
try {
    $env:EVE_LOOT_DATA = $testDataPath
    $appProcess = Start-Process -FilePath (Join-Path $targetPath 'EveLootAnalyzer.exe') -WindowStyle Hidden -PassThru
    Start-Sleep -Seconds 4
    $appProcess.Refresh()
    if ($appProcess.HasExited) { throw 'Installed application exited unexpectedly.' }
    # Hidden smoke-test windows are excluded by Process.CloseMainWindow.
    $closeWindowScript = @'
import ctypes,sys
user32=ctypes.windll.user32
expected=int(sys.argv[1]);found=[]
callback=ctypes.WINFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)
@callback
def visit(hwnd,param):
    pid=ctypes.c_ulong();user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
    title=ctypes.create_unicode_buffer(512);user32.GetWindowTextW(hwnd,title,512)
    if pid.value==expected and title.value.startswith('EVE'):
        found.append(hwnd);user32.PostMessageW(hwnd,0x0010,0,0)
    return True
user32.EnumWindows(visit,0)
assert found,'Application window missing'
'@
    $closeWindowScript | python - $appProcess.Id
    if ($LASTEXITCODE -ne 0) { throw 'Application window missing.' }
    if (-not $appProcess.WaitForExit(10000)) { throw 'Application did not close.' }
    if ($appProcess.ExitCode -ne 0) { throw 'Application failed.' }
    Write-Output 'Installed application launch passed.'
} finally { $env:EVE_LOOT_DATA = $previousDataPath }
$uninstallerPath = (Resolve-Path -LiteralPath (Join-Path $targetPath 'unins000.exe')).Path
if (-not $uninstallerPath.StartsWith($targetPath + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe uninstall target.' }
$uninstallProcess = Start-Process -FilePath $uninstallerPath -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -WindowStyle Hidden -Wait -PassThru
if ($uninstallProcess.ExitCode -ne 0) { throw 'Uninstall failed.' }
if (Test-Path -LiteralPath (Join-Path $targetPath 'EveLootAnalyzer.exe')) { throw 'Application was not removed.' }
if (-not (Test-Path -LiteralPath $sentinelPath)) { throw 'User data was removed.' }
if (-not (Test-Path -LiteralPath (Join-Path $testDataPath 'analyzer.sqlite3'))) { throw 'Database was removed.' }
Write-Output 'Uninstall passed; user data preserved.'
