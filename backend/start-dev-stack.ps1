$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $backendDir
$condaExe = "D:/anaconda/Scripts/conda.exe"
$pythonExe = "D:/anaconda/python.exe"

function Is-PortListening([int]$Port) {
  $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  return $null -ne $conn
}

Write-Host "Project root: $projectRoot" -ForegroundColor Cyan

# 1) Redis
if (-not (Is-PortListening 6379)) {
  $redisExe = Join-Path $backendDir "tools\redis\redis-server.exe"
  $redisConf = Join-Path $backendDir "tools\redis\redis.windows.conf"
  if (-not (Test-Path $redisExe)) {
    throw "Redis server not found: $redisExe"
  }

  if (Test-Path $redisConf) {
    Start-Process -FilePath $redisExe -ArgumentList "`"$redisConf`" --port 6379" -WindowStyle Minimized
  } else {
    Start-Process -FilePath $redisExe -WindowStyle Minimized
  }
  Start-Sleep -Seconds 1
  Write-Host "Redis started on 6379" -ForegroundColor Green
} else {
  Write-Host "Redis already running on 6379" -ForegroundColor Yellow
}

# 2) Celery worker
if (-not (Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "celery" -and $_.CommandLine -match "process_content_ingest" })) {
  $celeryCmd = "Set-Location '$backendDir'; `$env:CELERY_BROKER_URL='redis://127.0.0.1:6379/0'; `$env:CELERY_RESULT_BACKEND='redis://127.0.0.1:6379/1'; $condaExe run -p D:\anaconda --no-capture-output celery -A app.celery_client worker -l info -P solo"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $celeryCmd
  Write-Host "Celery worker started" -ForegroundColor Green
} else {
  Write-Host "Celery worker already running" -ForegroundColor Yellow
}

# 3) Flask backend
if (-not (Is-PortListening 5000)) {
  $backendCmd = "Set-Location '$projectRoot'; $pythonExe backend/app.py"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd
  Write-Host "Backend started on 5000" -ForegroundColor Green
} else {
  Write-Host "Backend already running on 5000" -ForegroundColor Yellow
}

# 4) Frontend static server
if (-not (Is-PortListening 5501)) {
  $frontendCmd = "Set-Location '$projectRoot'; $pythonExe -m http.server 5501 --directory frontend"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd
  Write-Host "Frontend started on 5501" -ForegroundColor Green
} else {
  Write-Host "Frontend already running on 5501" -ForegroundColor Yellow
}

Write-Host "" 
Write-Host "Dev stack ready" -ForegroundColor Green
Write-Host "Backend  : http://127.0.0.1:5000" -ForegroundColor Cyan
Write-Host "Frontend : http://127.0.0.1:5501/index.html" -ForegroundColor Cyan
Write-Host "Health   : http://127.0.0.1:5000/health" -ForegroundColor Cyan
