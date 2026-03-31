$ErrorActionPreference = "SilentlyContinue"

Write-Host "Stopping dev stack..." -ForegroundColor Yellow

# Stop process by listening ports (backend/frontend/redis)
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

# Stop celery related workers/process trees started in separate terminals
$celeryProcs = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match "celery" -or $_.CommandLine -match "app\.server:celery_client"
}
foreach ($proc in $celeryProcs) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped celery related process $($proc.ProcessId)" -ForegroundColor Green
}

# Stop backend package entry processes
$backendProcs = Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -match "-m app\.server"
}
foreach ($proc in $backendProcs) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped backend process $($proc.ProcessId)" -ForegroundColor Green
}

Write-Host "Dev stack stopped." -ForegroundColor Cyan
