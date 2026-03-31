$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $projectRoot "scripts/run_e2e_regression.ps1") @args
