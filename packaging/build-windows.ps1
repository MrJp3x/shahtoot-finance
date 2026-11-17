param([string]$Python = "python")

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Push-Location (Join-Path $PSScriptRoot "..")
try {
    $architecture = & $Python -c "import platform, sys; assert sys.platform == 'win32'; print(platform.machine())"
    if ($LASTEXITCODE -ne 0 -or $architecture -ne "AMD64") {
        throw "Run this build with x64 Python on Windows."
    }

    & $Python -m PyInstaller --noconfirm --windowed --onedir --noupx `
        --name ShahtootFinance --icon packaging/shahtoot.ico main.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

    $appFolder = Join-Path (Get-Location) "dist/ShahtootFinance"
    $executable = Join-Path $appFolder "ShahtootFinance.exe"
    $windowsPlugin = Get-ChildItem -Path $appFolder -Recurse -Filter "qwindows.dll" -File
    if (-not $windowsPlugin) { throw "The Qt Windows platform plugin was not packaged." }

    $previousPlatform = $env:QT_QPA_PLATFORM
    try {
        $env:QT_QPA_PLATFORM = "offscreen"
        $smoke = Start-Process -FilePath $executable -ArgumentList "--smoke-test" -PassThru
        if (-not $smoke.WaitForExit(45000)) {
            $smoke.Kill()
            throw "Packaged smoke test timed out."
        }
        if ($smoke.ExitCode -ne 0) { throw "Packaged smoke test failed with exit code $($smoke.ExitCode)." }
    }
    finally {
        $env:QT_QPA_PLATFORM = $previousPlatform
    }

    Copy-Item -LiteralPath "README.md" -Destination $appFolder
    Compress-Archive -LiteralPath $appFolder -DestinationPath "dist/ShahtootFinance-Windows-x64.zip" -Force
}
finally {
    Pop-Location
}
