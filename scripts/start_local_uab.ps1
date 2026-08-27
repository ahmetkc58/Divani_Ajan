param(
    [string]$PythonPath = "",
    [ValidatePattern('^(cpu|cuda|cuda:\d+)$')]
    [string]$EmbeddingDevice = "cuda:0",
    [switch]$DisableLlm
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($PythonPath)) {
    $pythonCandidates = @(
        (Join-Path $projectRoot ".venv\Scripts\python.exe"),
        (Join-Path (Split-Path -Parent $projectRoot) "work\jina-runtime\Scripts\python.exe")
    )
    $PythonPath = $pythonCandidates |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
}

if ([string]::IsNullOrWhiteSpace($PythonPath) -or -not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python 3.11+ ortamı bulunamadı. -PythonPath ile uygun yorumlayıcıyı verin."
}

$pythonVersion = & $PythonPath -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ([version]$pythonVersion -lt [version]"3.11") {
    throw "Bu proje Python 3.11+ gerektirir; bulunan sürüm: $pythonVersion"
}

$env:PYTHONPATH = Join-Path $projectRoot "src"
$env:KARAYOL_RETRIEVAL_MODE = "hybrid"
$env:KARAYOL_CORPUS_MODE = "competition_snapshot"
$env:KARAYOL_COMPETITION_SNAPSHOT_PATH = "data/processed/uab_legal_rag_v2_snapshot.json"
$env:KARAYOL_QDRANT_PATH = "runtime/uab-legal-rag-v2/qdrant"
$env:KARAYOL_QDRANT_COLLECTION = "uab_legal_leaf_v2"
$env:KARAYOL_QDRANT_VECTOR_NAME = "dense"
$env:KARAYOL_INDEX_VERSION = "2.0"
$env:KARAYOL_SNAPSHOT_RELEVANCE_POLICY = "lexical_overlap"
$env:KARAYOL_EMBEDDING_LOCAL_FILES_ONLY = "true"
$env:KARAYOL_EMBEDDING_DEVICE = $EmbeddingDevice
$env:KARAYOL_CORS_ALLOWED_ORIGINS = "http://127.0.0.1:3000,http://localhost:3000"
Remove-Item Env:QDRANT_URL -ErrorAction SilentlyContinue

if ($DisableLlm) {
    $env:KARAYOL_LLM_ENABLED = "false"
} else {
    $env:KARAYOL_LLM_ENABLED = "true"
}

Set-Location -LiteralPath $projectRoot
& $PythonPath -m uvicorn karayol_agent.api:app --host 127.0.0.1 --port 8010
