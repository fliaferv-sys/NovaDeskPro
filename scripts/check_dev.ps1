$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentFile = Join-Path $projectRoot ".env"
$pythonExecutable = Join-Path $projectRoot ".venv\Scripts\python.exe"
$manageScript = Join-Path $projectRoot "src\manage.py"
$sourceRoot = Join-Path $projectRoot "src"

Get-Content -LiteralPath $environmentFile | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith("#")) {
        $parts = $line.Split("=", 2)
        if ($parts.Count -eq 2) {
            [Environment]::SetEnvironmentVariable(
                $parts[0].Trim(),
                $parts[1].Trim(),
                "Process"
            )
        }
    }
}

Push-Location $sourceRoot
try {
    & $pythonExecutable $manageScript check
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & $pythonExecutable $manageScript makemigrations --check --dry-run
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & $pythonExecutable $manageScript test
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
