
# AIが使用するブラウザは、普段利用するブラウザとは分離している。
# 現在AI用にはChromiumを使用し、CDP経由で接続・操作する。

$ErrorActionPreference = "Stop"

$port = 9222
$profileDirectory = "Default"
$userDataDir = Join-Path $env:LOCALAPPDATA 'Chromium\Codex-CDP'
$cdpUrl = "http://127.0.0.1:$port/json/version"

try {
    $version = Invoke-RestMethod -Uri $cdpUrl -TimeoutSec 2
    if ($version.webSocketDebuggerUrl) {
        Write-Host "CDPで利用できるChromiumを再利用します: $cdpUrl"
        exit 0
    }
} catch {
    # CDPに接続できない場合だけChromiumを起動する。
    $null = $_
}

$chromiumCandidates = @(
    "C:\Program Files\chrome-win\chrome.exe",
    "${env:ProgramFiles}\chrome-win\chrome.exe",
    "${env:ProgramFiles(x86)}\chrome-win\chrome.exe"
)

$chromiumPath = $chromiumCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1

if (-not $chromiumPath) {
    throw "設定済みのChromium実行ファイルが見つかりません。"
}

$arguments = "--remote-debugging-address=127.0.0.1 --remote-debugging-port=$port --user-data-dir=`"$userDataDir`" --profile-directory=`"$profileDirectory`" --no-first-run --no-default-browser-check"

Start-Process -FilePath $chromiumPath -ArgumentList $arguments
Write-Host "ChromiumをCDP付きで起動しました: $cdpUrl (データ: $userDataDir、プロファイル: $profileDirectory)"
