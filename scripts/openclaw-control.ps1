[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet('start', 'stop', 'restart', 'cli')]
    [string]$Action,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$OpenClawArgs
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$runtimeRoot = Join-Path $projectRoot '.openclaw-runtime'
$nodeRoot = Join-Path $runtimeRoot 'node'
$cliRoot = Join-Path $runtimeRoot 'cli'
$nodePath = Join-Path $projectRoot '.openclaw-runtime\node\node.exe'
$cliEntryPath = Join-Path $projectRoot '.openclaw-runtime\cli\node_modules\openclaw\openclaw.mjs'
$openClawCommand = Join-Path $cliRoot 'openclaw.cmd'
$stateRoot = Join-Path $projectRoot '.openclaw'
$runtimeTempPath = Join-Path $runtimeRoot 'tmp'
$compileCachePath = Join-Path $runtimeRoot 'compile-cache'
$npmCachePath = Join-Path $runtimeRoot 'npm-cache'
$workspacePath = Join-Path $stateRoot 'workspace'
$logPath = Join-Path $runtimeTempPath 'openclaw-control.log'
$gatewayPort = 18789
$gatewayUrl = "http://127.0.0.1:$gatewayPort/"
$startupTimeoutSeconds = 90
$shutdownTimeoutSeconds = 330

# 操作日時、段階、結果をプロジェクト内ログへ記録する。
function Write-ControlLog {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet('INFO', 'WARN', 'ERROR')]
        [string]$Level,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff zzz'
    $safeMessage = $Message -replace '(?i)https?://[^\s"''<>]+', '[URL省略]' -replace '(?i)(token|password)([=: ]+)[^,\s"''}]+', '$1$2[省略]'
    $entry = "[$timestamp] [$Level] [$Action] $safeMessage"
    Add-Content -LiteralPath $logPath -Value $entry -Encoding UTF8
}

# プロジェクト内Node.jsでGatewayを実行中のプロセスを列挙する。
function Get-ProjectGatewayProcesses {
    $expectedNodePath = [System.IO.Path]::GetFullPath($nodePath)
    $expectedCliEntryPath = [System.IO.Path]::GetFullPath($cliEntryPath)

    @(
        Get-CimInstance Win32_Process -ErrorAction Stop |
            Where-Object {
                $normalizedCommandLine = if ($_.CommandLine) { $_.CommandLine.Replace('\\', '\') } else { '' }
                $_.ExecutablePath -and
                [string]::Equals(
                    [System.IO.Path]::GetFullPath($_.ExecutablePath),
                    $expectedNodePath,
                    [System.StringComparison]::OrdinalIgnoreCase
                ) -and
                $normalizedCommandLine -and
                $normalizedCommandLine.IndexOf($expectedCliEntryPath, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
                $normalizedCommandLine -match '(?i)\bgateway\s+run\b'
            }
    )
}

# ローカルGatewayポートを待ち受けているプロセスIDを取得する。
function Get-GatewayListenerProcessIds {
    @(
        Get-NetTCPConnection -LocalPort $gatewayPort -State Listen -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty OwningProcess -Unique
    )
}

# ポート所有者に一致するプロジェクトGatewayの起動元プロセスを特定する。
function Get-VerifiedGatewayTree {
    param(
        [int[]]$ListenerProcessIds,
        [switch]$AllowStartingProcess
    )

    $processes = @(Get-ProjectGatewayProcesses)
    if ($processes.Count -eq 0) {
        return $null
    }

    $processById = @{}
    foreach ($process in $processes) {
        $processById[[int]$process.ProcessId] = $process
    }

    if ($ListenerProcessIds.Count -gt 1) {
        return $null
    }

    $matchedProcess = $null
    if ($ListenerProcessIds.Count -gt 0) {
        if (-not $processById.ContainsKey([int]$ListenerProcessIds[0])) {
            return $null
        }
        $matchedProcess = $processById[[int]$ListenerProcessIds[0]]
    }
    elseif (-not $AllowStartingProcess) {
        return $null
    }

    if ($matchedProcess) {
        $rootProcess = $matchedProcess
        while ($processById.ContainsKey([int]$rootProcess.ParentProcessId)) {
            $rootProcess = $processById[[int]$rootProcess.ParentProcessId]
        }
        return [pscustomobject]@{
            Listener = $matchedProcess
            Root = $rootProcess
            Processes = $processes
        }
    }

    $candidateRoots = @(
        $processes | Where-Object { -not $processById.ContainsKey([int]$_.ParentProcessId) }
    )
    if ($candidateRoots.Count -ne 1) {
        return $null
    }

    [pscustomobject]@{
        Listener = $null
        Root = $candidateRoots[0]
        Processes = $processes
    }
}

# PIDを再確認し、プロジェクトGatewayと一致したプロセスだけを終了する。
function Test-ProjectGatewayProcessById {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId
    )

    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
    if (-not $process -or -not $process.ExecutablePath -or -not $process.CommandLine) {
        return $false
    }

    $normalizedCommandLine = $process.CommandLine.Replace('\\', '\')
    [string]::Equals(
        [System.IO.Path]::GetFullPath($process.ExecutablePath),
        [System.IO.Path]::GetFullPath($nodePath),
        [System.StringComparison]::OrdinalIgnoreCase
    ) -and
    $normalizedCommandLine.IndexOf([System.IO.Path]::GetFullPath($cliEntryPath), [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -and
    $normalizedCommandLine -match '(?i)\bgateway\s+run\b'
}

# Gatewayの通常停止を試し、応答しない場合だけ確認済みツリーを強制終了する。
function Stop-VerifiedGatewayProcess {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId,
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    if (-not (Test-ProjectGatewayProcessById -ProcessId $ProcessId)) {
        return
    }

    $taskkillPath = Join-Path $env:WINDIR 'System32\taskkill.exe'
    $null = & $taskkillPath /PID $ProcessId /T 2>$null
    $softStopExitCode = $LASTEXITCODE
    $softTimeout = if ($softStopExitCode -eq 0) { $TimeoutSeconds } else { 5 }
    $softDeadline = (Get-Date).AddSeconds($softTimeout)

    while ((Get-Date) -lt $softDeadline) {
        if (-not (Test-ProjectGatewayProcessById -ProcessId $ProcessId)) {
            return
        }
        Start-Sleep -Seconds 1
    }

    if (Test-ProjectGatewayProcessById -ProcessId $ProcessId) {
        Write-ControlLog -Level 'WARN' -Message "Gatewayの通常停止がタイムアウト。対象PIDを再確認して終了 (PID=$ProcessId, taskkillExit=$softStopExitCode)"
        $null = & $taskkillPath /PID $ProcessId /T /F 2>$null
        $forceDeadline = (Get-Date).AddSeconds(15)
        while ((Get-Date) -lt $forceDeadline) {
            if (-not (Test-ProjectGatewayProcessById -ProcessId $ProcessId)) {
                return
            }
            Start-Sleep -Seconds 1
        }
        throw "Gatewayプロセスを終了できませんでした (PID=$ProcessId)。"
    }
}

# GatewayのRPCヘルス応答を取得し、正常応答か判定する。
function Test-GatewayHealth {
    try {
        $healthOutput = @(& $openClawCommand gateway health --json --port $gatewayPort --timeout 5000 2>$null)
        $healthExitCode = $LASTEXITCODE
        if ($healthExitCode -ne 0) {
            return $false
        }

        $healthText = $healthOutput -join [Environment]::NewLine
        $jsonStart = $healthText.IndexOf('{')
        if ($jsonStart -lt 0) {
            return $false
        }

        $health = $healthText.Substring($jsonStart) | ConvertFrom-Json -ErrorAction Stop
        return [bool]$health.ok
    }
    catch {
        return $false
    }
}

# 起動後にGatewayのHTTP応答とRPCヘルスを確認する。
function Wait-GatewayReady {
    param(
        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $listenerProcessIds = @(Get-GatewayListenerProcessIds)
        if ($listenerProcessIds.Count -gt 0) {
            $verifiedTree = Get-VerifiedGatewayTree -ListenerProcessIds $listenerProcessIds
            if (-not $verifiedTree) {
                throw '18789番ポートの所有者がプロジェクトのGatewayではありません。別プロセスを停止せず中断します。'
            }

            $httpReady = $false
            try {
                $response = Invoke-WebRequest -Uri $gatewayUrl -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop
                $httpReady = $response.StatusCode -eq 200
            }
            catch {
                $httpReady = $false
            }

            if ($httpReady -and (Test-GatewayHealth)) {
                return $verifiedTree
            }
        }

        Start-Sleep -Seconds 1
    }

    throw "Gatewayが$TimeoutSeconds 秒以内に応答しませんでした。Gatewayの起動ログを確認してください。"
}

# Dashboard CLIから認証用URLを取得する。URL自体はログへ書き込まない。
function Get-DashboardBrowserUrl {
    $dashboardOutput = @(& $openClawCommand dashboard --json 2>$null)
    $dashboardExitCode = $LASTEXITCODE
    if ($dashboardExitCode -ne 0) {
        throw 'Control UIの認証用URLを取得できませんでした。Gateway状態とOpenClawログを確認してください。'
    }

    $dashboardText = $dashboardOutput -join [Environment]::NewLine
    $jsonStart = $dashboardText.IndexOf('{')
    if ($jsonStart -lt 0) {
        throw 'Control UIの認証用URLを読み取れませんでした。Gateway状態とOpenClawログを確認してください。'
    }

    try {
        $dashboard = $dashboardText.Substring($jsonStart) | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw 'Control UIの認証用URLを読み取れませんでした。Gateway状態とOpenClawログを確認してください。'
    }

    $browserUrl = [string]$dashboard.browserUrl
    $parsedUrl = $null
    if (
        -not $dashboard.ok -or
        -not [System.Uri]::TryCreate($browserUrl, [System.UriKind]::Absolute, [ref]$parsedUrl) -or
        $parsedUrl.Port -ne $gatewayPort -or
        $parsedUrl.Host -notin @('127.0.0.1', 'localhost') -or
        $parsedUrl.Scheme -notin @('http', 'https')
    ) {
        throw 'Control UIの認証用URLが不正か、発行できませんでした。Gateway状態とOpenClawログを確認してください。'
    }

    return $browserUrl
}

# 既存Gatewayを再利用するか、新規起動して正常応答まで待つ。
function Start-ProjectGateway {
    Write-ControlLog -Level 'INFO' -Message 'Gatewayの起動確認を開始'
    $listenerProcessIds = @(Get-GatewayListenerProcessIds)

    if ($listenerProcessIds.Count -gt 0) {
        $verifiedTree = Get-VerifiedGatewayTree -ListenerProcessIds $listenerProcessIds
        if (-not $verifiedTree) {
            throw '18789番ポートは別プロセスが使用中です。別プロセスを停止せず中断します。'
        }

        Write-ControlLog -Level 'INFO' -Message "プロジェクトGatewayを検出 (PID=$($verifiedTree.Listener.ProcessId))"
    }
    else {
        $existingProcesses = @(Get-ProjectGatewayProcesses)
        $pendingTree = Get-VerifiedGatewayTree -ListenerProcessIds @() -AllowStartingProcess
        if (-not $pendingTree) {
            if ($existingProcesses.Count -gt 0) {
                throw '起動中のプロジェクトGatewayを一意に識別できません。重複起動を避けるため中断します。'
            }
            $stdoutPath = Join-Path $runtimeTempPath ("gateway-{0}.out.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss'))
            $stderrPath = [System.IO.Path]::ChangeExtension($stdoutPath, '.err.log')
            $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $PSCommandPath + '" cli gateway run'
            $launcherPath = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
            $launcher = Start-Process -FilePath $launcherPath -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
            Write-ControlLog -Level 'INFO' -Message "プロジェクトGatewayを起動 (LauncherPID=$($launcher.Id))"
            Start-Sleep -Seconds 2
        }
        else {
            Write-ControlLog -Level 'INFO' -Message "Gateway起動中のプロジェクトプロセスを検出 (PID=$($pendingTree.Root.ProcessId))"
        }
    }

    $readyTree = Wait-GatewayReady -TimeoutSeconds $startupTimeoutSeconds
    Write-ControlLog -Level 'INFO' -Message "Gatewayが正常応答 (PID=$($readyTree.Listener.ProcessId))"

    $browserUrl = Get-DashboardBrowserUrl
    Write-ControlLog -Level 'INFO' -Message 'Control UI認証用URLを発行（URLは記録対象外）'
    Write-Host 'ブラウザで以下のURLを開いてください'
    Write-Host $browserUrl
}

# 確認済みプロジェクトGatewayを停止し、ポート解放を待つ。
function Stop-ProjectGateway {
    Write-ControlLog -Level 'INFO' -Message 'Gatewayの停止確認を開始'
    $listenerProcessIds = @(Get-GatewayListenerProcessIds)
    $existingProcesses = @(Get-ProjectGatewayProcesses)
    $verifiedTree = Get-VerifiedGatewayTree -ListenerProcessIds $listenerProcessIds -AllowStartingProcess

    if (-not $verifiedTree) {
        if ($listenerProcessIds.Count -gt 0) {
            throw '18789番ポートの所有者をプロジェクトGatewayと確認できません。別プロセスを停止せず中断します。'
        }
        if ($existingProcesses.Count -gt 0) {
            throw '停止対象のプロジェクトGatewayプロセスを一意に識別できません。プロセスを停止せず中断します。'
        }
        Write-ControlLog -Level 'INFO' -Message '停止対象のGatewayはありません'
        return
    }

    $listenerProcessId = if ($verifiedTree.Listener) { [int]$verifiedTree.Listener.ProcessId } else { $null }
    $rootProcessId = [int]$verifiedTree.Root.ProcessId

    if ($listenerProcessId) {
        Write-ControlLog -Level 'INFO' -Message "Gatewayを停止 (PID=$listenerProcessId)"
        Stop-VerifiedGatewayProcess -ProcessId $listenerProcessId -TimeoutSeconds $shutdownTimeoutSeconds
        Start-Sleep -Seconds 2
    }

    $listenerProcessIds = @(Get-GatewayListenerProcessIds)
    if ($listenerProcessIds.Count -gt 0) {
        $remainingTree = Get-VerifiedGatewayTree -ListenerProcessIds $listenerProcessIds
        if (-not $remainingTree) {
            throw '停止後に別プロセスが18789番ポートを使用しています。別プロセスを停止せず中断します。'
        }
        if ($listenerProcessId -and [int]$remainingTree.Listener.ProcessId -ne $listenerProcessId) {
            Write-ControlLog -Level 'WARN' -Message 'Gatewayの待ち受けPIDが変わりました。現在のプロジェクトGatewayを再確認して停止'
            Stop-VerifiedGatewayProcess -ProcessId ([int]$remainingTree.Listener.ProcessId) -TimeoutSeconds $shutdownTimeoutSeconds
            Start-Sleep -Seconds 2
        }
    }

    if ($rootProcessId -ne $listenerProcessId -and (Test-ProjectGatewayProcessById -ProcessId $rootProcessId)) {
        Write-ControlLog -Level 'INFO' -Message "Gateway起動プロセスを停止 (PID=$rootProcessId)"
        Stop-VerifiedGatewayProcess -ProcessId $rootProcessId -TimeoutSeconds 15
        Start-Sleep -Seconds 2
    }

    $listenerProcessIds = @(Get-GatewayListenerProcessIds)
    if ($listenerProcessIds.Count -gt 0) {
        $remainingTree = Get-VerifiedGatewayTree -ListenerProcessIds $listenerProcessIds
        if (-not $remainingTree) {
            throw '停止後に別プロセスが18789番ポートを使用しています。別プロセスを停止せず中断します。'
        }
        throw 'プロジェクトGatewayの待ち受けが残っています。プロジェクトログを確認してください。'
    }

    Start-Sleep -Seconds 2
    Write-ControlLog -Level 'INFO' -Message 'Gateway停止とポート解放を確認'
}

try {
    New-Item -ItemType Directory -Force -Path $runtimeTempPath, $compileCachePath, $stateRoot | Out-Null
    if (-not (Test-Path -LiteralPath $openClawCommand) -or -not (Test-Path -LiteralPath $nodePath) -or -not (Test-Path -LiteralPath $cliEntryPath)) {
        throw 'プロジェクト内のOpenClaw CLIまたはNode.jsが見つかりません。'
    }

    # OpenClaw、Node.js、npm、一時ファイルをプロジェクト内へ分離する。
    $env:PATH = "$nodeRoot;$cliRoot;$env:PATH"
    $env:OPENCLAW_HOME = $projectRoot
    $env:OPENCLAW_STATE_DIR = $stateRoot
    $env:OPENCLAW_CONFIG_PATH = Join-Path $stateRoot 'openclaw.json'
    $env:OPENCLAW_WORKSPACE_DIR = $workspacePath
    $env:NODE_COMPILE_CACHE = $compileCachePath
    $env:npm_config_cache = $npmCachePath
    $env:TEMP = $runtimeTempPath
    $env:TMP = $runtimeTempPath
    $env:TMPDIR = $runtimeTempPath

    if ($Action -eq 'cli') {
        if (-not $OpenClawArgs -or $OpenClawArgs.Count -eq 0) {
            throw 'cli の後に OpenClaw CLI のコマンドを指定してください。'
        }
        & $openClawCommand @OpenClawArgs
        exit $LASTEXITCODE
    }

    Write-ControlLog -Level 'INFO' -Message '操作を開始'
    switch ($Action) {
        'start' {
            Start-ProjectGateway
        }
        'stop' {
            Stop-ProjectGateway
        }
        'restart' {
            Stop-ProjectGateway
            Start-Sleep -Seconds 3
            Write-ControlLog -Level 'INFO' -Message '停止後の待機を完了。起動へ移行'
            Start-ProjectGateway
        }
    }
    Write-ControlLog -Level 'INFO' -Message '操作が完了'
}
catch {
    $errorType = $_.Exception.GetType().Name
    $errorMessage = $_.Exception.Message -replace '(?i)https?://[^\s"''<>]+', '[URL省略]' -replace '(?i)(token|password)([=: ]+)[^,\s"''}]+', '$1$2[省略]'
    Write-ControlLog -Level 'ERROR' -Message "$errorType`: $errorMessage"
    Write-Error $errorMessage
    exit 1
}
