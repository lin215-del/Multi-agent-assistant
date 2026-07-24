param(
    [ValidateSet("recommended", "all")]
    [string]$Scope = "all",
    [string]$BaseUrl = "http://localhost:8080",
    [string]$EmbeddingModel = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "JNU Student Assistant - Team RAGFlow Restore" -ForegroundColor Cyan
Write-Host "RAGFlow target: $BaseUrl"
Write-Host "Restore scope: $Scope"
Write-Host ""

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python was not found. Install Python 3.10 or newer first."
}

try {
    $null = Invoke-WebRequest -Uri "$($BaseUrl.TrimEnd('/'))/api/v1/datasets?page=1&page_size=1" -Method Get -TimeoutSec 10 -ErrorAction Stop
} catch {
    if ($_.Exception.Response.StatusCode.value__ -notin @(401, 403)) {
        throw "Cannot reach RAGFlow. Start Docker and verify that $BaseUrl opens."
    }
}

$secureKey = Read-Host "Enter the local RAGFlow API Key (not saved)" -AsSecureString
$pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
try {
    $env:RAGFLOW_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    $arguments = @(
        "scripts\restore_team_ragflow.py",
        "--base-url", $BaseUrl,
        "--scope", $Scope
    )
    if ($EmbeddingModel) {
        $arguments += @("--embedding-model", $EmbeddingModel)
    }
    & python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Knowledge-base restore failed. Review the error above."
    }
} finally {
    Remove-Item Env:\RAGFLOW_API_KEY -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
}

Write-Host ""
Write-Host "Restore requests submitted. Check the RAGFlow file list or logs for parsing progress." -ForegroundColor Green
