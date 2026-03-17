$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $backendDir

function Is-PortListening([int]$Port) {
  $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  return $null -ne $conn
}

function Test-PythonPath([string]$PathValue) {
  try {
    & $PathValue -c "import flask, flask_cors, requests" | Out-Null
    return $LASTEXITCODE -eq 0
  } catch {
    return $false
  }
}

function Resolve-PythonPath {
  $candidates = @()

  if ($env:FZG_PYTHON -and (Test-Path $env:FZG_PYTHON)) {
    $candidates += $env:FZG_PYTHON
  }

  $defaultCondaPy = "D:/anaconda/python.exe"
  if (Test-Path $defaultCondaPy) {
    $candidates += $defaultCondaPy
  }

  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd) {
    $candidates += $pythonCmd.Source
  }

  foreach ($candidate in $candidates | Select-Object -Unique) {
    if (Test-PythonPath $candidate) {
      return $candidate
    }
  }

  throw "No usable Python found with project dependencies. Please install requirements or set FZG_PYTHON to the right interpreter."
}

function Start-RedisIfNeeded {
  if (Is-PortListening 6379) {
    Write-Host "Redis already running on 6379" -ForegroundColor Yellow
    return $true
  }

  $redisExeCandidates = @()
  if ($env:FZG_REDIS_EXE) { $redisExeCandidates += $env:FZG_REDIS_EXE }
  $redisExeCandidates += (Join-Path $backendDir "tools\redis\redis-server.exe")

  foreach ($candidate in $redisExeCandidates | Select-Object -Unique) {
    if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path $candidate)) {
      $redisConf = Join-Path (Split-Path -Parent $candidate) "redis.windows.conf"
      if (Test-Path $redisConf) {
        Start-Process -FilePath $candidate -ArgumentList "`"$redisConf`" --port 6379" -WindowStyle Minimized
      } else {
        Start-Process -FilePath $candidate -ArgumentList "--port 6379" -WindowStyle Minimized
      }
      Start-Sleep -Seconds 1
      if (Is-PortListening 6379) {
        Write-Host "Redis started on 6379 ($candidate)" -ForegroundColor Green
        return $true
      }
    }
  }

  $redisPathCmd = Get-Command redis-server -ErrorAction SilentlyContinue
  if ($redisPathCmd) {
    Start-Process -FilePath "redis-server" -ArgumentList "--port 6379" -WindowStyle Minimized
    Start-Sleep -Seconds 1
    if (Is-PortListening 6379) {
      Write-Host "Redis started on 6379 (PATH redis-server)" -ForegroundColor Green
      return $true
    }
  }

  Write-Host "Redis not available. Skip Redis/Celery in portable mode." -ForegroundColor DarkYellow
  return $false
}

$pythonPath = Resolve-PythonPath
$pythonPathEscaped = $pythonPath.Replace("'", "''")

Write-Host "Project root: $projectRoot" -ForegroundColor Cyan
Write-Host "Python exe : $pythonPath" -ForegroundColor Cyan

$redisReady = Start-RedisIfNeeded

# 2) Celery worker
if ($redisReady) {
  $celeryRunning = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match "celery" -and $_.CommandLine -match "app\.celery_client"
  }

  if (-not $celeryRunning) {
    $celeryCmd = "Set-Location '$backendDir'; `$env:CELERY_BROKER_URL='redis://127.0.0.1:6379/0'; `$env:CELERY_RESULT_BACKEND='redis://127.0.0.1:6379/1'; & '$pythonPathEscaped' -m celery -A app.celery_client worker -l info -P solo"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $celeryCmd
    Write-Host "Celery worker started" -ForegroundColor Green
  } else {
    Write-Host "Celery worker already running" -ForegroundColor Yellow
  }
} else {
  Write-Host "Celery skipped because Redis is unavailable" -ForegroundColor DarkYellow
}

# 3) Flask backend
if (-not (Is-PortListening 5000)) {
  $backendCmd = "Set-Location '$projectRoot'; & '$pythonPathEscaped' backend/app.py"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd
  Start-Sleep -Seconds 2
  if (Is-PortListening 5000) {
    Write-Host "Backend started on 5000" -ForegroundColor Green
  } else {
    Write-Host "Backend start attempted but 5000 is not listening (check dependency/env in backend window)" -ForegroundColor DarkYellow
  }
} else {
  Write-Host "Backend already running on 5000" -ForegroundColor Yellow
}

# 4) Frontend static server
if (-not (Is-PortListening 5501)) {
  $frontendCmd = "Set-Location '$projectRoot'; & '$pythonPathEscaped' -m http.server 5501 --directory frontend"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd
  Write-Host "Frontend started on 5501" -ForegroundColor Green
} else {
  Write-Host "Frontend already running on 5501" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Portable dev stack ready" -ForegroundColor Green
Write-Host "Backend  : http://127.0.0.1:5000" -ForegroundColor Cyan
Write-Host "Frontend : http://127.0.0.1:5501/index.html" -ForegroundColor Cyan
Write-Host "Health   : http://127.0.0.1:5000/health" -ForegroundColor Cyan
