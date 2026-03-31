$backendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $backendDir "scripts/start-dev-stack-portable.ps1") @args
