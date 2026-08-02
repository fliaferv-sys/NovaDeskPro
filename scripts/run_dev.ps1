param(
    [string]$Address = "127.0.0.1",
    [int]$Port = 8000
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentFile = Join-Path $projectRoot ".env"
$pythonExecutable = Join-Path $projectRoot ".venv\Scripts\python.exe"
$manageScript = Join-Path $projectRoot "src\manage.py"
$sourceRoot = Join-Path $projectRoot "src"

if (-not (Test-Path -LiteralPath $environmentFile)) {
    throw "No existe $environmentFile. Copie .env.example y configure sus valores."
}

if (-not (Test-Path -LiteralPath $pythonExecutable)) {
    throw "No existe .venv. Cree el entorno e instale requirements.txt."
}

Get-Content -LiteralPath $environmentFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) {
        return
    }

    $parts = $line.Split("=", 2)
    if ($parts.Count -eq 2) {
        [Environment]::SetEnvironmentVariable(
            $parts[0].Trim(),
            $parts[1].Trim(),
            "Process"
        )
    }
}

Push-Location $sourceRoot
try {
    & $pythonExecutable $manageScript runserver "${Address}:${Port}"
}
finally {
    Pop-Location
}
