param(
    [string]$PythonPath = "",
    [string]$OllamaUrl = "http://127.0.0.1:11434",
    [string]$OllamaModel = "qwen2.5:0.5b"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $projectRoot ".env"

if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $pythonCandidates = @(
        (Join-Path $projectRoot ".venv\Scripts\python.exe"),
        (Join-Path (Split-Path -Parent $projectRoot) "work\jina-runtime\Scripts\python.exe")
    )
    $PythonPath = $pythonCandidates |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    if ([string]::IsNullOrWhiteSpace($PythonPath)) {
        $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
        if ($null -ne $pythonCommand) {
            $PythonPath = $pythonCommand.Source
        }
    }
}

if ([string]::IsNullOrWhiteSpace($PythonPath) -or -not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python bulunamadı. .venv oluşturun veya -PythonPath ile Python 3.11+ yolunu verin."
}

if (Test-Path -LiteralPath $envFile) {
    foreach ($line in Get-Content -LiteralPath $envFile) {
        $trimmed = $line.Trim().TrimStart([char]0xFEFF)
        if (-not $trimmed -or $trimmed.StartsWith("#")) {
            continue
        }
        $separatorIndex = $trimmed.IndexOf("=")
        if ($separatorIndex -lt 1) {
            throw ".env içinde geçersiz satır bulundu."
        }
        $name = $trimmed.Substring(0, $separatorIndex)
        $value = $trimmed.Substring($separatorIndex + 1)
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
    }
}

$uri = [Uri]$OllamaUrl
if ($uri.Scheme -notin @("http", "https") -or $uri.Host -notin @("localhost", "127.0.0.1", "::1")) {
    throw "Ollama URL yalnız yerel loopback adresi olabilir."
}

$tags = Invoke-RestMethod -Uri ($OllamaUrl.TrimEnd("/") + "/api/tags") -Method Get -TimeoutSec 5
$installedModels = @($tags.models | ForEach-Object { $_.name })
if ($OllamaModel -notin $installedModels) {
    throw "Ollama modeli kurulu değil: $OllamaModel. Önce 'ollama pull $OllamaModel' çalıştırın."
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
$env:KARAYOL_LLM_PROVIDER = "ollama"
$env:KARAYOL_LLM_MODEL = $OllamaModel
$env:KARAYOL_LLM_BASE_URL = $OllamaUrl.TrimEnd("/")
$env:KARAYOL_RETRIEVAL_MODE = "hybrid"
$env:KARAYOL_CORPUS_MODE = "competition_snapshot"
$env:KARAYOL_COMPETITION_SNAPSHOT_PATH = "data/processed/competition_snapshot.json"
$env:KARAYOL_QDRANT_PATH = "runtime/qdrant-competition-snapshot"
$env:KARAYOL_QDRANT_COLLECTION = "competition_snapshot_chunks_v1"
$env:KARAYOL_EMBEDDING_LOCAL_FILES_ONLY = "true"
$env:KARAYOL_EMBEDDING_DEVICE = "cpu"
Remove-Item Env:QDRANT_URL -ErrorAction SilentlyContinue

Set-Location -LiteralPath $projectRoot
& $PythonPath -m uvicorn karayol_agent.api:app --host 127.0.0.1 --port 8010
