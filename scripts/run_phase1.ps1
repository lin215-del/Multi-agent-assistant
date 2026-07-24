param(
  [int]$MaxPages = 80,
  [int]$Depth = 2
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

python crawler\jnu_crawler.py --max-pages $MaxPages --depth $Depth
python cleaner\clean_jnu_docs.py

Write-Host "Phase 1 finished."
Write-Host "Cleaned JSONL: $ProjectRoot\data\cleaned\documents.jsonl"
Write-Host "RAGFlow Markdown: $ProjectRoot\data\cleaned\ragflow_markdown"
Write-Host "Downloaded files: $ProjectRoot\data\files"
