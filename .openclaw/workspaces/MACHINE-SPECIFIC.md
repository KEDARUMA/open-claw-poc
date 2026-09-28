# MACHINE-SPECIFIC

<!-- 動作しているPC固有の設定をここに記述 -->

- 動作しているこのPCは 'Windows 11 Home'
- パスに含まれる `\` はパス区切りとして扱い、エスケープ文字として削除・置換・結合しない。
<!-- codex 0.156.1 のバグの一時対応 -->
- ユーザーがチャットでパスをコードブロック外に貼り付けた場合は、文字列が変わる可能性を警告し、そのパスを処理に使わず、半角バッククォート3つのコードブロック内で再提示するよう求める。
- コードブロック内で提示されたパスは、受信した文字列を一字一句そのまま使い、文字や区切りを追加・削除・置換・分割しない。
- Codex Appのパス入力不具合に関する報告（修正状況確認用）: https://github.com/openai/codex/issues/41486

## ブラウザの使用
- ブラウザ操作は Chromium のみを使う。
- ブラウザ操作は、対象タブの webSocketDebuggerUrl へ直接 CDP 接続して行う。Playwright などの操作ライブラリを介さない。
- ブラウザ接続全般で MCP 接続は禁止し、明示的な別指示がない限り CDP 直接接続に統一する。
- `Runtime.evaluate` の `expression` と、ブラウザ実行用テンプレートリテラル内部は純粋なJavaScriptに限定する。TypeScriptの型注釈・型アサーション（`as ...`）・interface・type・enum・import・exportなどを含めない。実行前に評価文字列を静的確認し、ブラウザ実行可能なJavaScriptであることを確認する。
- 新たな作業を始める場合はNew tab/New windowを起動し作業を開始する。
- ユーザがブラウザでの作業を指示する場合はおおむね今ブラウザで開いてるタブの事を指している。ユーザの指示とブラウザの表示内容が当てはまらない場合は作業を進めずにユーザに指示を仰ぐこと。
- Codexが作成したタブは作成時のページハンドルで管理し、用途完了後に個別で閉じる。ユーザー所有タブ、未処理タブ、認証・対象不一致などの問題確認用タブは閉じない。URLやドメイン一致による一括クローズは禁止する。
- Google Calendar の操作は必ず MCP を使うこと。ブラウザフォールバックしないこと。
- Gmail の操作は必ず MCP を使うこと、ブラウザ使用でのフォールバックは絶対しないこと。

### Chromiumの起動

- 起動するときは、このプロジェクトの `scripts/launch-browser-codex.ps1` をPowerShellから実行する。
- スクリプトは起動前に `http://127.0.0.1:9222/json/version` を確認する。`webSocketDebuggerUrl` が取得できた場合は、すでに起動しているChromiumを再利用し、別のブラウザーを起動しない。既存タブが作業に必要な場合がある。
- CDP接続を確認できない場合に限り、設定済みのChromiumを起動する。
- PowerShellでは、ユーザーデータディレクトリを環境変数 `LOCALAPPDATA` から次のように組み立てる。

  ```powershell
  $userDataDir = Join-Path $env:LOCALAPPDATA 'Chromium\Codex-CDP'
  ```

- 起動時は次の引数を使う。

  ```text
  --remote-debugging-address=127.0.0.1
  --remote-debugging-port=9222
  --user-data-dir="$userDataDir"
  --profile-directory="Default"
  --no-first-run
  --no-default-browser-check
  ```

- スクリプトに設定されたChromium実行ファイルだけを使う。デバッグポートは `9222`、ユーザーデータディレクトリは上記のパス、プロファイルは `Default` に固定する。
- 認証またはCDP接続に失敗した場合は作業を中止し、問題を報告して判断を仰ぐ。

### ページ操作開始タイミング
- 対象は、Codexが新規タブを作成したページ、またはURL遷移させたページに限る。既に表示済みのページにはこの判定処理を差し込まない。
- 新規タブ作成またはURL遷移の前に、CDPのページイベント購読を開始する。
- 対象の`targetId`、メインフレームの`frameId`、最新遷移の`loaderId`を保持し、ページ状態を遷移単位で管理する。
- `Page.frameNavigated`または`Page.frameStartedNavigating`で最新のメインフレーム遷移を記録する。
- 最新遷移の後に、同じメインフレームの`Page.frameStoppedLoading`を受信した時点をページ操作開始可能とする。
- `Page.loadEventFired`と同一`loaderId`の`Page.lifecycleEvent("load")`は記録するが、ページ操作開始の必須条件にはしない。
- `Page.navigatedWithinDocument`を受信した同一ドキュメント内のURL変更は、`SAME_DOCUMENT_READY`としてページ操作を開始できる。
- 複数回遷移した場合は最新遷移だけを有効とし、古い遷移のイベントで操作を開始してはならない。
- `networkIdle`、`document.readyState`、DOM要素の有無、固定時間待機、ポーリング、タイムアウト後の強行開始を、ページ操作開始判定に使用してはならない。
- `Network.loadingFailed`やHTTPステータスはページ操作開始の停止条件にせず、個別通信の記録に限定する。
- ボタン、一覧、入力欄など個別操作対象の存在確認は、ページ操作開始後に各処理が行う。`Page.frameStoppedLoading`、`Page.loadEventFired`、`document.readyState`だけでSPA・遅延描画の完了とみなしてはならず、MutationObserver等のイベント駆動で対象要素の描画を確認してから取得・操作する。対象要素を確認できない場合は「不一致」や「取得失敗」と断定せず、「対象確認不能」として停止する。
