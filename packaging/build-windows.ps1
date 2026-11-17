param([string]$Python = "python")

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Push-Location (Join-Path $PSScriptRoot "..")
try {
    $platform = & $Python -c "import sysconfig; print(sysconfig.get_platform())"
    if ($LASTEXITCODE -ne 0 -or $platform -ne "win-amd64") {
        throw "Run this build with x64 Python on Windows."
    }

    & $Python -m PyInstaller --noconfirm --windowed --onefile --noupx `
        --name ShahtootFinance --icon packaging/shahtoot.ico main.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

    $executable = Join-Path (Get-Location) "dist/ShahtootFinance.exe"
    $archiveMembers = & $Python -m PyInstaller.utils.cliutils.archive_viewer --list --brief $executable
    if ($LASTEXITCODE -ne 0 -or -not ($archiveMembers -match 'qwindows\.dll$')) {
        throw "The Qt Windows platform plugin was not packaged."
    }

    $previousPlatform = $env:QT_QPA_PLATFORM
    try {
        $env:QT_QPA_PLATFORM = "offscreen"
        $smoke = Start-Process -FilePath $executable -ArgumentList "--smoke-test" -PassThru
        if (-not $smoke.WaitForExit(90000)) {
            $smoke.Kill()
            throw "Packaged smoke test timed out."
        }
        if ($smoke.ExitCode -ne 0) { throw "Packaged smoke test failed with exit code $($smoke.ExitCode)." }
    }
    finally {
        $env:QT_QPA_PLATFORM = $previousPlatform
    }

    Write-Output "Windows executable: $executable"
}
finally {
    Pop-Location
}
