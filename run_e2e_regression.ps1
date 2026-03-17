$base = "http://127.0.0.1:5000"
$uid = "reg4_$(Get-Date -Format 'yyyyMMddHHmmss')"
$results = @()
$planId = $null
$ingestTaskId = $null

function Add-Result($name, $ok, $detail) {
    $script:results += [PSCustomObject]@{
        name = $name
        ok = [bool]$ok
        detail = [string]$detail
    }
}

function Parse-ApiError($err) {
    try {
        if ($err.ErrorDetails -and $err.ErrorDetails.Message) {
            return ($err.ErrorDetails.Message | ConvertFrom-Json)
        }
    } catch {}
    return $null
}

function New-JsonBody([object]$obj) {
    return ($obj | ConvertTo-Json -Depth 12)
}

function Invoke-JsonApi {
    param(
        [Parameter(Mandatory = $true)][string]$Method,
        [Parameter(Mandatory = $true)][string]$Url,
        [object]$Body
    )

    $args = @{
        Uri = $Url
        Method = $Method
        Headers = @{ "Content-Type" = "application/json" }
        TimeoutSec = 30
    }

    if ($PSBoundParameters.ContainsKey("Body")) {
        $args.Body = New-JsonBody $Body
    }

    try {
        $resp = Invoke-RestMethod @args
        return @{ ok = $true; body = $resp; err = $null }
    } catch {
        $parsedErr = Parse-ApiError $_
        return @{ ok = $false; body = $parsedErr; err = $_ }
    }
}

function Wait-TaskResult {
    param(
        [Parameter(Mandatory = $true)][string]$TaskId,
        [int]$MaxAttempts = 25,
        [int]$SleepSeconds = 1
    )

    for ($i = 1; $i -le $MaxAttempts; $i++) {
        $r = Invoke-JsonApi -Method "GET" -Url "$base/api/tasks/$TaskId"
        if (-not $r.ok) {
            return @{ ok = $false; state = "REQUEST_FAILED"; detail = (($r.body | ConvertTo-Json -Depth 6) -as [string]) }
        }

        $state = [string]($r.body.state)
        if ($state -in @("SUCCESS", "FAILURE", "REVOKED")) {
            return @{ ok = $true; state = $state; body = $r.body }
        }

        Start-Sleep -Seconds $SleepSeconds
    }

    return @{ ok = $false; state = "TIMEOUT"; detail = "task polling timeout" }
}

function Add-ResultFromApi {
    param(
        [string]$Name,
        [hashtable]$ApiResult,
        [scriptblock]$OnSuccess,
        [scriptblock]$OnFailure
    )

    if ($ApiResult.ok) {
        $detail = if ($OnSuccess) { & $OnSuccess $ApiResult.body } else { "ok" }
        Add-Result $Name $true $detail
        return
    }

    $detail = if ($OnFailure) {
        & $OnFailure $ApiResult.body
    } elseif ($ApiResult.body) {
        ($ApiResult.body | ConvertTo-Json -Depth 6 -Compress)
    } else {
        [string]$ApiResult.err
    }
    Add-Result $Name $false $detail
}

$r = Invoke-JsonApi -Method "GET" -Url "$base/health"
Add-ResultFromApi -Name "health" -ApiResult $r -OnSuccess { param($b) [string]$b.status }

$r = Invoke-JsonApi -Method "GET" -Url "$base/api/plans?user_id=$uid"
Add-ResultFromApi -Name "plans.get" -ApiResult $r -OnSuccess { param($b) "count=$($b.count)" }

$r = Invoke-JsonApi -Method "POST" -Url "$base/api/plans" -Body @{
    user_id = $uid
    time = "09:30"
    task = "e2e calculus review"
}
if ($r.ok -and $r.body.plan -and $r.body.plan.id) {
    $script:planId = [string]$r.body.plan.id
    Add-Result "plans.post" $true "id=$planId"
} else {
    Add-Result "plans.post" $false (($r.body | ConvertTo-Json -Depth 6 -Compress) -as [string])
}

if ($planId) {
    $r = Invoke-JsonApi -Method "PUT" -Url "$base/api/plans/$planId" -Body @{ user_id = $uid; completed = $true }
    Add-ResultFromApi -Name "plans.put" -ApiResult $r
} else {
    Add-Result "plans.put" $false "skip: no plan_id"
}

if ($planId) {
    $r = Invoke-JsonApi -Method "DELETE" -Url "$base/api/plans/$planId" -Body @{ user_id = $uid }
    Add-ResultFromApi -Name "plans.delete" -ApiResult $r
} else {
    Add-Result "plans.delete" $false "skip: no plan_id"
}

$r = Invoke-JsonApi -Method "POST" -Url "$base/api/ask" -Body @{ user_id = $uid; question = "" }
if (-not $r.ok -and $r.body -and [string]$r.body.error_code -eq "INVALID_INPUT") {
    Add-Result "ask.invalid" $true "code=INVALID_INPUT"
} else {
    Add-Result "ask.invalid" $false (($r.body | ConvertTo-Json -Depth 6 -Compress) -as [string])
}

$r = Invoke-JsonApi -Method "POST" -Url "$base/api/ask" -Body @{ user_id = $uid; question = "what is derivative" }
Add-ResultFromApi -Name "ask.valid" -ApiResult $r -OnSuccess { param($b) "source=$($b.source)" }

$r = Invoke-JsonApi -Method "POST" -Url "$base/api/content/ingest_async" -Body @{
    user_id = $uid
    content_type = "note"
    title = "e2e note"
    content = "derivative depends on limit and integral"
    source = "regression"
}
if ($r.ok -and $r.body.task_id) {
    $script:ingestTaskId = [string]$r.body.task_id
    Add-Result "ingest.async" $true "task=$ingestTaskId"
} else {
    Add-Result "ingest.async" $false (($r.body | ConvertTo-Json -Depth 6 -Compress) -as [string])
}

if ($ingestTaskId) {
    $poll = Wait-TaskResult -TaskId $ingestTaskId -MaxAttempts 30 -SleepSeconds 1
    if ($poll.ok) {
        Add-Result "tasks.poll" ($poll.state -eq "SUCCESS") $poll.state
    } else {
        Add-Result "tasks.poll" $false "$($poll.state): $($poll.detail)"
    }
} else {
    Add-Result "tasks.poll" $false "skip: no task_id"
}

$r = Invoke-JsonApi -Method "GET" -Url "$base/api/knowledge_graph?user_id=$uid"
Add-ResultFromApi -Name "graph.get" -ApiResult $r -OnSuccess { param($b) "nodes=$($b.node_count)" }

$r = Invoke-JsonApi -Method "POST" -Url "$base/api/knowledge_graph/extract" -Body @{
    user_id = $uid
    text = "function derivative and limit relation"
    source = "regression"
}
Add-ResultFromApi -Name "graph.extract" -ApiResult $r -OnSuccess { param($b) "new=$($b.new_concept_count)" }

$r = Invoke-JsonApi -Method "POST" -Url "$base/api/knowledge_graph/mastery" -Body @{
    user_id = $uid
    concept = "derivative"
    mastery = 0.62
}
Add-ResultFromApi -Name "graph.mastery" -ApiResult $r

$r = Invoke-JsonApi -Method "GET" -Url "$base/api/knowledge_graph/path?user_id=$uid&target=derivative"
Add-ResultFromApi -Name "graph.path" -ApiResult $r -OnSuccess { param($b) "len=$($b.length)" }

$r = Invoke-JsonApi -Method "POST" -Url "$base/api/diagnosis/analyze" -Body @{
    user_id = $uid
    question = "given f(x)=x^2 find derivative"
    correct_answer = "2x"
    user_answer = "x"
}
Add-ResultFromApi -Name "diagnosis.analyze" -ApiResult $r

$r = Invoke-JsonApi -Method "GET" -Url "$base/api/diagnosis/report?user_id=$uid"
Add-ResultFromApi -Name "diagnosis.report" -ApiResult $r

$r = Invoke-JsonApi -Method "GET" -Url "$base/api/profile?user_id=$uid"
Add-ResultFromApi -Name "profile.get" -ApiResult $r

$r = Invoke-JsonApi -Method "GET" -Url "$base/api/recommendations?user_id=$uid&limit=3"
Add-ResultFromApi -Name "recommendations.get" -ApiResult $r -OnSuccess { param($b) "count=$($b.count)" }

$r = Invoke-JsonApi -Method "GET" -Url "$base/api/dashboard/summary?user_id=$uid"
Add-ResultFromApi -Name "dashboard.summary" -ApiResult $r

try {
    $resp = Invoke-RestMethod -Uri "$base/api/upload_image" -Method Post -Body @{ user_id = $uid } -TimeoutSec 30
    Add-Result "upload.invalid" $false "unexpected success: $($resp | ConvertTo-Json -Depth 4 -Compress)"
} catch {
    $parsedErr = Parse-ApiError $_
    if ($parsedErr -and [string]$parsedErr.error_code -eq "INVALID_INPUT") {
        Add-Result "upload.invalid" $true "code=INVALID_INPUT"
    } else {
        Add-Result "upload.invalid" $false (($parsedErr | ConvertTo-Json -Depth 6 -Compress) -as [string])
    }
}

$total = $results.Count
$passed = @($results | Where-Object { $_.ok }).Count
$failed = $total - $passed
$passRate = if ($total -gt 0) { [math]::Round(($passed * 100.0) / $total, 2) } else { 0 }

$summary = [PSCustomObject]@{
    user_id = $uid
    total = $total
    passed = $passed
    failed = $failed
    pass_rate = $passRate
    items = $results
}

$summaryPath = Join-Path $PSScriptRoot "e2e_summary.json"
$summary | ConvertTo-Json -Depth 10 | Set-Content -Encoding UTF8 $summaryPath

Write-Host ("E2E done. total={0} passed={1} failed={2} pass_rate={3}%" -f $total, $passed, $failed, $passRate)
Write-Host "summary: $summaryPath"