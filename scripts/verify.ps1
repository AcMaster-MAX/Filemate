$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

Push-Location $projectRoot
try {
    uv sync --extra dev
    uv run ruff check server.py main.py filemate/execution `
        filemate/tests/test_storage.py `
        filemate/tests/test_file_ops.py `
        filemate/tests/test_archiver.py `
        filemate/tests/test_confirmation_executor.py `
        filemate/tests/test_server_persistence.py
    uv run pytest filemate/tests -q -m "not e2e"

    Push-Location (Join-Path $projectRoot "filemate/web")
    try {
        npm ci
        npm run build
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}
