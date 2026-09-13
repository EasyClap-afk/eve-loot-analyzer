param(
    [string]$OutputDirectory = 'dist-v1.6',
    [string]$Version = '1.6',
    [string]$Compiler = ''
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$appDirectory = Join-Path $OutputDirectory 'EveLootAnalyzer'
if (-not (Test-Path -LiteralPath (Join-Path $appDirectory 'EveLootAnalyzer.exe'))) {
    throw 'Build the app with build.ps1 first.'
}
if (-not $Compiler) {
    $availableCompiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($availableCompiler) { $Compiler = $availableCompiler.Source }
    else {
        $candidates = @(
            (Join-Path $PSScriptRoot 'build\tools\InnoSetup\ISCC.exe'),
            "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
            "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
        )
        $Compiler = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    }
}
if (-not $Compiler) { throw 'Install Inno Setup 6, or pass -Compiler with the path to ISCC.exe.' }
Copy-Item -LiteralPath 'README.md' -Destination $appDirectory -Force
$sourcePath = (Resolve-Path -LiteralPath $appDirectory).Path
$outputPath = (Resolve-Path -LiteralPath $OutputDirectory).Path
& $Compiler "/DAppVersion=$Version" "/DSourceDir=$sourcePath" "/O$outputPath" 'installer\EveLootAnalyzer.iss'
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
$installerPath = Join-Path $outputPath "EveLootAnalyzer-Setup-$Version.exe"
$digest = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
"$digest  $([IO.Path]::GetFileName($installerPath))" | Set-Content -LiteralPath "$installerPath.sha256" -Encoding ASCII
Write-Output $installerPath
