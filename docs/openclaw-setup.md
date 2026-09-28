# OpenClaw セットアップ手順

## 目的と対象

OpenClawは、自分で管理する環境でAIアシスタントを動かし、チャットから仕事を頼める基盤です。チャット接続とAI社員の実行を担う常駐プロセスをGateway、状態確認や操作を行うブラウザー画面をControl UIと呼びます。

ターミナルから指示文書に沿って作業を進めるツール（Codex CLI）を使い、Windows 11 の本プロジェクトに OpenClaw を導入します。Codex サブスクリプション認証、導入後のログ・動作確認、Gateway 起動、Control UI 表示までを扱います。

- Ollama は導入・使用しません。
- OpenClaw の Node.js、CLI、設定、状態、キャッシュ、実行ログは、このプロジェクト内に置きます。
- OpenClaw 標準の Control UI を対象とします。AI社員専用の状態管理・操作アプリはこの手順に含めません。
- 既存の `.openclaw` 設定・認証・状態を削除、初期化、または上書きしません。
- Windows のユーザープロファイル、グローバル PATH、グローバル Node.js / OpenClaw のインストール先は変更しません。
- Codex または ChatGPT の認証操作が必要な場合は、そこで止めてユーザーに案内します。

## Codex からの一括実行

PowerShell でプロジェクトルート（このリポジトリを配置したディレクトリ）に移動してから、次のコマンドを実行します。

```powershell
codex exec --approve-for-me --cd . "docs/openclaw-setup.md を最初から読み、この文書と AGENTS.md の指示に従ってセットアップを実行してください。認証など人の操作が必要なら、その地点で停止して操作方法を案内してください。"
```

`--approve-for-me` は Codex CLI の自動レビュー付き実行モードです。プロジェクト外へ書き込む操作や、ここに記載していない破壊的操作を追加しないでください。

## このプロジェクトの現在の構成

2026-09-27 時点で、次の構成を確認しています。

| 項目 | プロジェクト内の場所・値 |
| --- | --- |
| OpenClaw CLI | `.openclaw-runtime/cli` |
| OpenClaw の版 | `2026.9.6` |
| 専用 Node.js | `.openclaw-runtime/node`、`26.10.0` |
| OpenClaw 状態・設定 | `.openclaw` |
| OpenClaw CLI・Gateway制御 | `scripts/openclaw-control.ps1` |
| Gateway / Control UI | `http://127.0.0.1:18789/` |

`scripts/openclaw-control.ps1` は、OpenClaw CLI の実行環境と、設定・作業領域・Node.js・npm キャッシュ・一時ファイルの場所をプロジェクト内へ設定します。`start`、`stop`、`restart` で Gateway を制御し、`cli` の後に CLI コマンドを指定すると OpenClaw の各コマンドを実行します。`.gitignore` には `.openclaw` と `.openclaw-runtime` の除外パターンがあります。

```powershell
.\scripts\openclaw-control.ps1 start
.\scripts\openclaw-control.ps1 stop
.\scripts\openclaw-control.ps1 restart
.\scripts\openclaw-control.ps1 cli models status --check
```

## 実行手順

### 1. 指示と対象を確認

1. プロジェクトと Codex の `AGENTS.md`、`MACHINE-SPECIFIC.md` を読み、指示を守ります。
2. `git rev-parse --show-toplevel` でGitルートを特定し、そのルートに `docs/openclaw-setup.md` と `scripts/openclaw-control.ps1` があることを確認します。どちらかがない場合は停止します。
3. `.openclaw` と `.openclaw-runtime` が既にある場合は内容を保持し、削除・初期化しません。
4. Gateway の状態と 18789 番ポートを確認します。別プロセスがポートを使用している場合、プロセスを終了せず停止して報告します。

### 2. プロジェクト内に Node.js と OpenClaw CLI を用意

まず `scripts/openclaw-control.ps1`、`.openclaw-runtime/node/node.exe`、`.openclaw-runtime/cli/openclaw.cmd` の有無と版を確認します。Node.js がない場合だけ公式インストーラーを使い、OpenClaw CLI がない場合だけ npm で導入します。既存の Node.js が `26.10.0` 以外、または OpenClaw CLI が `2026.9.6` 以外なら、上書きせず停止して報告します。

```powershell
$projectRoot = (Get-Location).Path
$runtimeRoot = Join-Path $projectRoot '.openclaw-runtime'
$nodeRoot = Join-Path $runtimeRoot 'node'
$cliRoot = Join-Path $runtimeRoot 'cli'
$installerPath = Join-Path $runtimeRoot 'install-v2026.9.6.ps1'
$env:npm_config_cache = Join-Path $runtimeRoot 'npm-cache'
New-Item -ItemType Directory -Force -Path $runtimeRoot,$cliRoot | Out-Null

if (-not (Test-Path -LiteralPath (Join-Path $nodeRoot 'node.exe'))) {
    if (-not (Test-Path -LiteralPath $installerPath)) {
        Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/openclaw/openclaw/v2026.9.6/scripts/install.ps1' -OutFile $installerPath
    }
    & $installerPath -NodeOnly -NodePrefix $nodeRoot -NodeVersion '26.10.0'
}

$nodeVersion = (& (Join-Path $nodeRoot 'node.exe') --version).TrimStart('v')
if ($nodeVersion -ne '26.10.0') { throw "想定外のNode.js版です: $nodeVersion" }
$env:PATH = "$nodeRoot;$cliRoot;$env:PATH"
$packageJson = Join-Path $cliRoot 'node_modules/openclaw/package.json'
$openclawCommand = Join-Path $cliRoot 'openclaw.cmd'
if (-not (Test-Path -LiteralPath $packageJson) -or -not (Test-Path -LiteralPath $openclawCommand)) {
    & (Join-Path $nodeRoot 'npm.cmd') install --global --prefix $cliRoot 'openclaw@2026.9.6'
    if ($LASTEXITCODE -ne 0) { throw 'OpenClaw CLI のインストールに失敗しました。' }
}
$openclawVersion = (Get-Content -LiteralPath $packageJson | ConvertFrom-Json).version
if ($openclawVersion -ne '2026.9.6') { throw "想定外のOpenClaw版です: $openclawVersion" }
```

この `--global` は `--prefix` で指定した `.openclaw-runtime/cli` の中だけに適用します。システム全体の npm prefix や PATH は変更しません。

### 3. Codex サブスクリプション認証を確認

CLI は常に `scripts/openclaw-control.ps1 cli` 経由で実行します。既存の `gateway.mode`、モデル、認証状態を先に確認し、既に設定済みの項目を上書きしません。

モデル認証が存在しない、または利用できない場合は、次のコマンドを案内してそこで停止します。

```powershell
.\scripts\openclaw-control.ps1 cli models auth login --provider openai --device-code
```

ユーザーが表示されたデバイスコードを使ってサインインを完了した後、上記の `codex exec` コマンドをもう一度実行します。認証情報を画面やログへ転記しません。

Gateway のモードが未設定の場合に限り `gateway.mode=local` を設定します。モデルが未設定の場合に限り、公式 OpenAI/Codex サブスクリプションのモデル `openai/gpt-6-astra` を既定値にします。認証状態は `scripts/openclaw-control.ps1 cli models status --check` で確認し、トークンを出力するコマンドは使いません。

`models status --check` の終了コード `1` は認証またはランタイムの問題、`2` は認証期限が近い状態を示します。`2` は即時の認証失敗として扱わず、表示された状態を報告します。

未設定の値だけを次のコマンドで設定します。既存値がある場合は変更しません。

```powershell
$configPath = Join-Path (Get-Location).Path '.openclaw/openclaw.json'
$config = if (Test-Path -LiteralPath $configPath) { Get-Content -Raw -LiteralPath $configPath | ConvertFrom-Json } else { [pscustomobject]@{} }
if ([string]::IsNullOrWhiteSpace([string]$config.gateway.mode)) {
    .\scripts\openclaw-control.ps1 cli config set gateway.mode local
    if ($LASTEXITCODE -ne 0) { throw 'Gateway mode の設定に失敗しました。' }
}
if ([string]::IsNullOrWhiteSpace([string]$config.agents.defaults.model.primary)) {
    .\scripts\openclaw-control.ps1 cli config set agents.defaults.model.primary openai/gpt-6-astra
    if ($LASTEXITCODE -ne 0) { throw '既定モデルの設定に失敗しました。' }
}
.\scripts\openclaw-control.ps1 cli config validate
if ($LASTEXITCODE -ne 0) { throw 'OpenClaw 設定の検証に失敗しました。' }
.\scripts\openclaw-control.ps1 cli models status --check
if ($LASTEXITCODE -gt 2) { throw 'Codex 認証状態を確認できませんでした。' }
```

### 4. Gateway と Control UI を起動し、ログを確認

1. `gateway status --require-rpc` が正常なら既存プロセスを再利用します。正常でない場合は18789番ポートを確認し、別プロセスが使用中なら停止して報告します。ポートが空いている場合だけ、プロジェクト内ログへ出力してGatewayをバックグラウンド起動します。隠しウィンドウで起動し、Windowsサービスは登録しません。

   ```powershell
   $projectRoot = (Get-Location).Path
   $runtimeRoot = Join-Path $projectRoot '.openclaw-runtime'
   $controlPath = Join-Path $projectRoot 'scripts/openclaw-control.ps1'
   & $controlPath cli gateway status --require-rpc --timeout 5000 *> $null
   if ($LASTEXITCODE -eq 0) {
       Write-Output '既存のGatewayを再利用します。'
   } else {
       $listener = Get-NetTCPConnection -LocalPort 18789 -State Listen -ErrorAction SilentlyContinue
       if ($listener) { throw 'Gateway status は異常ですが、18789番ポートは使用中です。プロセスを終了せず停止します。' }
       $logRoot = Join-Path $runtimeRoot 'tmp'
       New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
       $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
       $arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + $controlPath + '" cli gateway run'
       Start-Process -FilePath (Get-Command pwsh -ErrorAction Stop).Source -ArgumentList $arguments -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logRoot "gateway-$stamp.out.log") -RedirectStandardError (Join-Path $logRoot "gateway-$stamp.err.log")
       Write-Output 'Gatewayをバックグラウンドで起動しました。'
   }
   ```

2. Gateway状態、Control UIのHTTP応答、OpenClaw実行ログを次のコマンドで確認します。Gateway statusの終了コードが0、HTTP応答が200、ログファイルが空でないことを成功条件とします。

   ```powershell
  $projectRoot = (Get-Location).Path
  $controlPath = Join-Path $projectRoot 'scripts/openclaw-control.ps1'
  $logRoot = Join-Path $projectRoot '.openclaw-runtime/tmp/openclaw'
  $runtimeLogRoot = Join-Path $projectRoot '.openclaw-runtime/tmp'
  $deadline = [TimeSpan]::FromSeconds(60)
  $watch = [System.Diagnostics.Stopwatch]::StartNew()
  $ready = $false
  while ($watch.Elapsed -lt $deadline) {
      & $controlPath cli gateway status --require-rpc --timeout 2000 *> $null
      $gatewayReady = $LASTEXITCODE -eq 0
      $httpReady = $false
      $remainingSeconds = [Math]::Floor(($deadline - $watch.Elapsed).TotalSeconds)
      if ($remainingSeconds -gt 0) {
          $timeoutSeconds = [Math]::Max(1, [Math]::Min(2, [int]$remainingSeconds))
          try {
              $response = Invoke-WebRequest -Uri 'http://127.0.0.1:18789/' -TimeoutSec $timeoutSeconds -ErrorAction Stop
              $httpReady = $response.StatusCode -eq 200
          } catch {
              $httpReady = $false
          }
      }
      if ($gatewayReady -and $httpReady) {
          $ready = $true
          break
      }
      $remainingMilliseconds = [Math]::Floor(($deadline - $watch.Elapsed).TotalMilliseconds)
      if ($remainingMilliseconds -gt 0) { Start-Sleep -Milliseconds ([int][Math]::Min(1000, $remainingMilliseconds)) }
  }
  if (-not $ready) { throw "Gateway または Control UI が60秒以内に起動しませんでした。ログを確認してください: $runtimeLogRoot" }
  $logFile = Get-ChildItem -LiteralPath $logRoot -Filter 'openclaw-*.log' -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
  if (-not $logFile -or $logFile.Length -le 0) { throw "OpenClaw の実行ログがないか、空です: $logRoot" }
  $logFile | Select-Object FullName,Length,LastWriteTime
   ```

   新規起動時は `.openclaw-runtime/tmp/gateway-<起動時刻>.out.log` と `.err.log` も確認します。既存 Gateway を再利用する場合は再起動せず、既存ログの場所と更新時刻を記録します。起動エラーまたはタイムアウト時はログを調べて報告し、別ポートへ勝手に切り替えません。
3. ブラウザー起動・接続は `$launch-browser-codex` の手順に従い、Chromium だけを使います。ブラウザー接続には CDP を直接使います。
4. `scripts/openclaw-control.ps1 cli dashboard --json` の `browserUrl` を使って Control UI を開きます。このURLには短時間だけ有効な認証情報が含まれるため、コンソール・ログ・ファイル・最終回答に値を出しません。ブラウザーの画面遷移前にCDPイベントを購読します。
5. Control UI の読み込みを確認し、タブを開いたままにします。Gateway も停止しません。

### 5. 完了報告

次の結果を報告します。

- OpenClaw / Node.js の版と配置先
- Codex 認証の状態（秘密情報は含めない）
- Gateway 状態、HTTP 応答、ログの確認結果
- Gateway の稼働状態と Control UI の URL
- 手動操作が残った場合は、その内容

## 公式資料

- [OpenClaw v2026.9.6 install.ps1](https://github.com/openclaw/openclaw/blob/v2026.9.6/scripts/install.ps1) — Node.js のプロジェクト内配置に使う公式インストーラー
- [OpenAI / Codex 認証手順（v2026.9.6）](https://github.com/openclaw/openclaw/blob/v2026.9.6/docs/providers/openai/setup.md)
- [Dashboard CLI 手順（v2026.9.6）](https://github.com/openclaw/openclaw/blob/v2026.9.6/docs/cli/dashboard.md)
