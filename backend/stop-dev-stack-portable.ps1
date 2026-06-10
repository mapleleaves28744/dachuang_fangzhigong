$backendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $backendDir "scripts/stop-dev-stack-portable.ps1") @args
