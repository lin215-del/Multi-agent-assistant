param(
    [int]$WaitMinutes = 10
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$Cloudflared = "C:\Program Files (x86)\cloudflared\cloudflared.exe"
if (-not (Test-Path $Cloudflared)) {
    throw "cloudflared is not installed."
}

$deadline = (Get-Date).AddMinutes($WaitMinutes)
do {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8080" -Method Get -UseBasicParsing -TimeoutSec 10
        if ($response.StatusCode -ge 200) {
            break
        }
    } catch {
        Start-Sleep -Seconds 10
    }
} while ((Get-Date) -lt $deadline)

if ((Get-Date) -ge $deadline) {
    throw "RAGFlow did not become ready within $WaitMinutes minutes."
}

Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
$stamp = Get-Date -Format "yyyyMMddHHmmss"
$stdout = Join-Path $ProjectRoot "outputs\cloudflared-$stamp.out.log"
$stderr = Join-Path $ProjectRoot "outputs\cloudflared-$stamp.err.log"
$process = Start-Process -FilePath $Cloudflared `
    -ArgumentList @("tunnel", "--url", "http://localhost:8080", "--protocol", "http2", "--edge-ip-version", "4", "--no-autoupdate") `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr `
    -PassThru

$tunnelDeadline = (Get-Date).AddMinutes(2)
$url = ""
do {
    Start-Sleep -Seconds 2
    $log = (Get-Content $stdout, $stderr -Raw -ErrorAction SilentlyContinue) -join "`n"
    $match = [regex]::Match($log, "https://[a-z0-9-]+\.trycloudflare\.com")
    if ($match.Success) {
        $url = $match.Value
        break
    }
} while ((Get-Date) -lt $tunnelDeadline -and -not $process.HasExited)

if (-not $url) {
    throw "Cloudflare quick tunnel did not return a public URL."
}

$apiDeadline = (Get-Date).AddMinutes(2)
do {
    try {
        $response = Invoke-WebRequest -Uri $url -Method Get -UseBasicParsing -TimeoutSec 20
        if ($response.StatusCode -ge 200) {
            break
        }
    } catch {
        Start-Sleep -Seconds 5
    }
} while ((Get-Date) -lt $apiDeadline)

if ((Get-Date) -ge $apiDeadline) {
    throw "Cloudflare tunnel is not reachable."
}

$url | pnpm dlx vercel env update RAGFLOW_BASE_URL production --yes
if ($LASTEXITCODE -ne 0) {
    throw "Failed to update the Vercel RAGFLOW_BASE_URL."
}

pnpm dlx vercel --prod --yes
if ($LASTEXITCODE -ne 0) {
    throw "Vercel production deployment failed."
}

$state = @{
    updated_at = (Get-Date).ToString("s")
    tunnel_url = $url
    cloudflared_pid = $process.Id
}
$state | ConvertTo-Json | Set-Content (Join-Path $ProjectRoot "outputs\shared_ragflow_state.json") -Encoding utf8
