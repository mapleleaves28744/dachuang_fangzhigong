$ErrorActionPreference = "SilentlyContinue"

Write-Host "Stopping portable dev stack..." -ForegroundColor Yellow

# Stop by key listening ports
$ports = @(5000, 5501, 6379)
foreach ($port in $ports) {
  $connections = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if ($connections) {
    $ids = $connections | Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($id in $ids) {
      Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
      Write-Host "Stopped process $id on port $port" -ForegroundColor Green
    }
  } else {
    Write-Host "No listener on port $port" -ForegroundColor DarkYellow
  }
}

# Stop celery workers
$celeryProcs = Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match "celery" -or $_.CommandLine -match "app\.celery_client"
}
foreach ($proc in $celeryProcs) {
  Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
  Write-Host "Stopped celery related process $($proc.ProcessId)" -ForegroundColor Green
}

# Stop extra backend python processes that run backend/app.py
$backendProcs = Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -match "backend[\\/]app.py"
}
foreach ($proc in $backendProcs) {
  Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
  Write-Host "Stopped backend process $($proc.ProcessId)" -ForegroundColor Green
}

Write-Host "Portable dev stack stopped." -ForegroundColor Cyan
