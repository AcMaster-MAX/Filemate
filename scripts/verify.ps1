$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

function Assert-LastExitCode {
    param([Parameter(Mandatory = $true)][string]$Step)

    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

Push-Location $projectRoot
try {
    uv sync --extra dev
    Assert-LastExitCode "uv sync"
    uv run ruff check server.py main.py filemate/execution `
        filemate/tests/test_storage.py `
        filemate/tests/test_file_ops.py `
        filemate/tests/test_archiver.py `
        filemate/tests/test_confirmation_executor.py `
        filemate/tests/test_server_persistence.py `
        filemate/tests/test_retrieval.py `
        filemate/tests/test_study.py `
        filemate/study `
        filemate/understanding/interview.py `
        filemate/understanding/retrieval.py `
        evaluation/run_evaluation.py `
        evaluation/analyze_study.py `
        evaluation/analyze_feedback.py
    Assert-LastExitCode "Ruff"
    uv run pytest filemate/tests -q -m "not e2e"
    Assert-LastExitCode "pytest"

    Push-Location (Join-Path $projectRoot "filemate/web")
    try {
        npm ci
        Assert-LastExitCode "npm ci"
        npm run build
        Assert-LastExitCode "frontend build"
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}
