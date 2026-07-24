param(
    [string[]]$Path,
    [int]$Limit = 0,
    [switch]$Refresh
)

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtime = if ($env:MINERU_RUNTIME_DIR) { $env:MINERU_RUNTIME_DIR } else { "D:\student-assistant-runtime" }
$env:MINERU_RUNTIME_DIR = $runtime
$env:MINERU_EXECUTABLE = Join-Path $runtime "mineru-venv\Scripts\mineru.exe"
$env:HF_HOME = Join-Path $runtime "huggingface"
$env:MODELSCOPE_CACHE = Join-Path $runtime "modelscope"
$env:XDG_CACHE_HOME = Join-Path $runtime "cache"
$env:TEMP = Join-Path $runtime "tmp"
$env:TMP = $env:TEMP

$arguments = @("$projectRoot\multimodal\mineru_pipeline.py")
if ($Path) { $arguments += $Path }
if ($Limit -gt 0) { $arguments += @("--limit", "$Limit") }
if ($Refresh) { $arguments += "--refresh" }

python @arguments
$parseExitCode = $LASTEXITCODE
python "$projectRoot\ragflow\import_mineru.py"
$importExitCode = $LASTEXITCODE
if ($importExitCode -ne 0) { exit $importExitCode }
if ($parseExitCode -ne 0) { exit $parseExitCode }
