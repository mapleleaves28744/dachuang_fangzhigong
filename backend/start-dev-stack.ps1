$ErrorActionPreference = "Stop"

$backendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $backendDir
$envFile = Join-Path $backendDir ".env"
$condaExe = "D:/anaconda/Scripts/conda.exe"
$pythonExe = "D:/anaconda/python.exe"

function Resolve-PythonExe {
  if (Test-Path $pythonExe) { return $pythonExe }
  $pyCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pyCmd) { return $pyCmd.Source }
  throw "Python executable not found. Please install Python or update start-dev-stack.ps1"
}

function Ensure-PythonDeps([string]$PyExe) {
  $checkCmd = "import flask, flask_cors, neo4j, celery, redis, sqlalchemy; print('ok')"
  & $PyExe -c $checkCmd *> $null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "Python dependencies ready" -ForegroundColor Green
    return
  }

  Write-Host "Installing backend dependencies from requirements.txt ..." -ForegroundColor Yellow
  Push-Location $backendDir
  try {
    & $PyExe -m pip install -r requirements.txt
  } finally {
    Pop-Location
  }
}

function Is-PortListening([int]$Port) {
  $conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  return $null -ne $conn
}

function Get-EnvValue([string]$Key, [string]$DefaultValue = "") {
  $v = [Environment]::GetEnvironmentVariable($Key, "Process")
  if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }

  $v = [Environment]::GetEnvironmentVariable($Key, "User")
  if (-not [string]::IsNullOrWhiteSpace($v)) { return $v }

  if (Test-Path $envFile) {
    $line = Get-Content $envFile -ErrorAction SilentlyContinue | Where-Object { $_ -match "^\s*$Key\s*=" } | Select-Object -First 1
    if ($line) {
      $parts = $line.Split('=', 2)
      if ($parts.Count -eq 2) {
        return $parts[1].Trim().Trim('"').Trim("'")
      }
    }
  }

  return $DefaultValue
}

function Test-TcpPort([string]$HostName, [int]$Port) {
  try {
    $client = New-Object System.Net.Sockets.TcpClient
    $iar = $client.BeginConnect($HostName, $Port, $null, $null)
    $ok = $iar.AsyncWaitHandle.WaitOne(1200, $false)
    if (-not $ok) {
      $client.Close()
      return $false
    }
    $client.EndConnect($iar)
    $client.Close()
    return $true
  } catch {
    return $false
  }
}

function Get-UriHostPort([string]$UriText, [int]$DefaultPort = 7687) {
  if ([string]::IsNullOrWhiteSpace($UriText)) {
    return @{"host"=""; "port"=$DefaultPort}
  }

  $m = [regex]::Match($UriText, "^[a-zA-Z][a-zA-Z0-9+.-]*://([^/:]+)(:(\d+))?")
  if ($m.Success) {
    $h = $m.Groups[1].Value
    $p = $DefaultPort
    if ($m.Groups[3].Success) { $p = [int]$m.Groups[3].Value }
    return @{"host"=$h; "port"=$p}
  }

  return @{"host"=""; "port"=$DefaultPort}
}

Write-Host "Project root: $projectRoot" -ForegroundColor Cyan
$redisReady = $false
$pythonExe = Resolve-PythonExe
Write-Host "Python: $pythonExe" -ForegroundColor Cyan
Ensure-PythonDeps $pythonExe

# 0) 存储后端提示（M1）
$storageBackend = (Get-EnvValue "STORAGE_BACKEND" "json").ToLower()
$databaseUrl = Get-EnvValue "DATABASE_URL" ""
if ($storageBackend -eq "sql") {
  Write-Host "Storage backend: sql" -ForegroundColor Cyan
  if ($databaseUrl -match "mysql(\+pymysql)?://[^@/]+@([^:/]+)(:(\d+))?/") {
    $mysqlHost = $Matches[2]
    $mysqlPort = 3306
    if ($Matches[4]) { $mysqlPort = [int]$Matches[4] }
    if (Test-TcpPort $mysqlHost $mysqlPort) {
      Write-Host "MySQL reachable at ${mysqlHost}:${mysqlPort}" -ForegroundColor Green
    } else {
      Write-Host "MySQL NOT reachable at ${mysqlHost}:${mysqlPort} (sql 模式可能启动失败)" -ForegroundColor DarkYellow
    }
  } elseif ([string]::IsNullOrWhiteSpace($databaseUrl)) {
    Write-Host "DATABASE_URL 未设置，将使用后端默认 sqlite:///data/fzg.db" -ForegroundColor Yellow
  } else {
    Write-Host "DATABASE_URL 未识别为 MySQL，当前值: $databaseUrl" -ForegroundColor Yellow
  }
} else {
  Write-Host "Storage backend: json" -ForegroundColor Cyan
}

# 0.5) Neo4j 可用性提示（尽量确保“全服务”）
$useNeo4jRaw = (Get-EnvValue "USE_NEO4J" "auto").ToLower()
$neo4jUri = Get-EnvValue "NEO4J_URI" ""
$neo4jProbe = Get-UriHostPort $neo4jUri 7687
if ($useNeo4jRaw -in @("true", "1", "on", "yes", "auto")) {
  if (-not [string]::IsNullOrWhiteSpace($neo4jProbe.host)) {
    if (Test-TcpPort $neo4jProbe.host $neo4jProbe.port) {
      Write-Host "Neo4j reachable at $($neo4jProbe.host):$($neo4jProbe.port)" -ForegroundColor Green
    } else {
      Write-Host "Neo4j NOT reachable at $($neo4jProbe.host):$($neo4jProbe.port) (图谱服务可能降级)" -ForegroundColor DarkYellow
    }
  } else {
    Write-Host "USE_NEO4J=$useNeo4jRaw but NEO4J_URI is empty" -ForegroundColor DarkYellow
  }
}

# 1) Redis
if (-not (Is-PortListening 6379)) {
  $redisExe = Join-Path $backendDir "tools\redis\redis-server.exe"
  $redisConf = Join-Path $backendDir "tools\redis\redis.windows.conf"
  if (-not (Test-Path $redisExe)) {
    Write-Host "Redis server not found, skip Redis: $redisExe" -ForegroundColor DarkYellow
  } else {
    if (Test-Path $redisConf) {
      Start-Process -FilePath $redisExe -ArgumentList "`"$redisConf`" --port 6379" -WindowStyle Minimized
    } else {
      Start-Process -FilePath $redisExe -WindowStyle Minimized
    }
    Start-Sleep -Seconds 1

    if (Is-PortListening 6379) {
      $redisReady = $true
      Write-Host "Redis started on 6379" -ForegroundColor Green
    } else {
      Write-Host "Redis start attempted but 6379 is not listening" -ForegroundColor DarkYellow
    }
  }
} else {
  $redisReady = $true
  Write-Host "Redis already running on 6379" -ForegroundColor Yellow
}

# 2) Celery worker
if ($redisReady) {
  if (-not (Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "celery" -and $_.CommandLine -match "process_content_ingest" })) {
    $celeryCmd = "Set-Location '$backendDir'; `$env:CELERY_BROKER_URL='redis://127.0.0.1:6379/0'; `$env:CELERY_RESULT_BACKEND='redis://127.0.0.1:6379/1'; & '$pythonExe' -m celery -A app.celery_client worker -l info -P solo"
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $celeryCmd
    Write-Host "Celery worker started" -ForegroundColor Green
  } else {
    Write-Host "Celery worker already running" -ForegroundColor Yellow
  }
} else {
  Write-Host "Redis unavailable, skip Celery worker" -ForegroundColor DarkYellow
}

# 3) Flask backend
if (-not (Is-PortListening 5000)) {
  $backendCmd = "Set-Location '$projectRoot'; & '$pythonExe' backend/app.py"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd
  Write-Host "Backend started on 5000" -ForegroundColor Green
} else {
  Write-Host "Backend already running on 5000" -ForegroundColor Yellow
}

# 4) Frontend static server
if (-not (Is-PortListening 5501)) {
  $frontendCmd = "Set-Location '$projectRoot'; & '$pythonExe' -m http.server 5501 --directory frontend"
  Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd
  Write-Host "Frontend started on 5501" -ForegroundColor Green
} else {
  Write-Host "Frontend already running on 5501" -ForegroundColor Yellow
}

# 5) 启动后健康检查（检查是否“全服务”可用）
$health = $null
for ($i = 1; $i -le 10; $i++) {
  try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:5000/health" -TimeoutSec 3
    if ($health -and $health.status -eq "ok") {
      break
    }
  } catch {
    Start-Sleep -Seconds 1
  }
}

if ($health -and $health.status -eq "ok") {
  Write-Host "Health check: OK" -ForegroundColor Green
  Write-Host ("health => storage={0}, celery={1}, neo4j={2}, ai={3}" -f $health.storage_backend, $health.celery_enabled, $health.neo4j_enabled, $health.ai_enabled) -ForegroundColor Cyan
} else {
  Write-Host "Health check failed after retries" -ForegroundColor DarkYellow
}

Write-Host "" 
Write-Host "Dev stack ready" -ForegroundColor Green
Write-Host "Backend  : http://127.0.0.1:5000" -ForegroundColor Cyan
Write-Host "Frontend : http://127.0.0.1:5501/index.html" -ForegroundColor Cyan
Write-Host "Health   : http://127.0.0.1:5000/health" -ForegroundColor Cyan
