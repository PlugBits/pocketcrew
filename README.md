# ポケクル(Pocket Crew)

スマホから自分の md を読める。リンクをタップで開ける。

Claude Code のスレ(tmux で動いている作業セッション)を、スマホのホーム画面に置ける小さな PWA から見て、送って、通知を受け取るための自宅サーバーです。API キーは要りません。手元の Claude Code サブスクリプションと tmux をそのまま使います。

## できること

- **ホーム画面**: tmux で動いている Claude Code のスレ一覧・状態(動作中/待機/停止)をスマホで見る
- **送信**: スレにメッセージを送る。既存のプリセット(役割ごとの初期プロンプト)を選んで新しいスレを開ける
- **プッシュ通知**: スレの状態が変わったら iPhone/Android に通知(Web Push。サーバー証明書とブラウザの通知許可だけで動く)
- **自動復帰**: サーバーやスレが落ちても、名簿(`sessions.json`)から自動で立て直す
- **vault ビューア**: `~/vault` のような Markdown フォルダをスマホでそのまま読む。チャット本文に出てくる `~/vault/....md` のようなリンクをタップすると、その場で開く(これが一番の見どころです)
- **room で機能を足す**: `rooms/` の下にフォルダを1つ作るだけで、ページ・API・定時ジョブを追加できる。付属の `workout`(ワークアウト記録)・`plan`(タスク/予定ダッシュボード)・`daily`(日次まとめ)・`vault` が実例です

## スクリーンショット

(準備中。撮り次第ここに貼ります)

- `docs/img/home.png` — ホーム画面(スレ一覧)
- `docs/img/thread.png` — スレの画面(送信・⋯メニュー)
- `docs/img/vault.png` — vault ビューア(md を開いた状態)

## 必要なもの

- Claude Code が使えるサブスクリプション(Claude Pro/Max など)。Anthropic の API キーは不要 — tmux 越しに Claude Code の CLI へ文字を送るだけなので、課金は普段の Claude Code 利用と同じです
- tmux
- Python 3.11 以上(標準ライブラリの `tomllib` を使うため)
- Python パッケージ `cryptography`(プッシュ通知の VAPID 鍵・暗号化に使用。他は標準ライブラリのみ)
- (任意)スマホから見るなら [Tailscale](https://tailscale.com/) — 自宅の外からでも自分の端末にだけ安全にアクセスできる

## 導入

```sh
git clone https://github.com/PlugBits/pocketcrew.git
cd pocketcrew
pip install --user cryptography
cp config.example.toml config.toml
```

`config.toml` を開いて、最低限 `[paths] vault` (Markdown を置いているフォルダ)と `[tmux] session` (Claude Code のスレを並べる tmux セッション名)を自分の環境に合わせます。他の項目は既定値のままで動きます。

いきなり起動して試すだけなら:

```sh
python3 server.py
```

`http://127.0.0.1:8787/` を開けば、その場で動きます(常駐させたい場合は下の手順へ)。

### WSL / Linux(systemd --user で常駐)

```sh
mkdir -p ~/.config/systemd/user
cp deploy/pocketcrew.service ~/.config/systemd/user/pocketcrew.service
systemctl --user daemon-reload
systemctl --user enable --now pocketcrew
```

WSL でログイン時に自動起動させたいときは `loginctl enable-linger $USER` を1回実行してください。詳細は [`deploy/README.md`](deploy/README.md)。

### Mac(launchd で常駐)

```sh
sed -i '' 's#/PATH/TO/pocketcrew#'"$HOME"'/pocketcrew#g' deploy/com.pocketcrew.plist
cp deploy/com.pocketcrew.plist ~/Library/LaunchAgents/com.pocketcrew.plist
launchctl load ~/Library/LaunchAgents/com.pocketcrew.plist
```

詳細は [`deploy/README.md`](deploy/README.md)。

## スマホから見る(Tailscale)

1. 自宅サーバーとスマホの両方に [Tailscale](https://tailscale.com/) を入れて同じ tailnet に参加させる
2. `config.toml` の `[server] bind` を `127.0.0.1` から Tailscale の IP(`100.x.y.z`。`tailscale ip -4` で確認)に変える
3. HTTPS で見たい場合(PWA のプッシュ通知には HTTPS が必要です)は、`[server] hostname` に Tailscale が割り当てた名前(`tailscale status` や Tailscale 管理画面で確認できる `xxxx.tailnet-name.ts.net` の形)を設定し、サーバー機で1度だけ証明書を取得します:
   ```sh
   tailscale cert --cert-file certs/fullchain.pem --key-file certs/privkey.pem <hostname>
   ```
   サーバーはこの証明書があれば `https_port`(既定 8443)で自動的に HTTPS を待ち受けます
4. スマホの Safari/Chrome で `https://<hostname>:8443/` を開き、共有メニューから「ホーム画面に追加」。これで通常のアプリのようにアイコンから開けます(PWA)
5. 通知を受け取りたい場合は、開いた画面で通知を許可し、⋯メニューの通知設定から「テスト送信」を1回試してください

Tailscale に接続していない(自宅の外で VPN オフ)ときは届きません。それ以外は普通の自宅サーバーと同じです。

## room の足し方

room は `rooms/` の下のフォルダ1つです。フォルダを作って `room.json` を置くだけで、ホーム画面の⋯メニューに現れ、`/<room名>` で専用ページを持てます。詳しい契約(どのファイルが何をするか)は [`CLAUDE.md`](CLAUDE.md) にまとめてあります。

### 手動で作る

1. `cp -r rooms/_template rooms/<room名>`(自分だけで使うなら `rooms-private/<room名>` でも良い。`rooms-private/` は gitignore 済みで公開されません)
2. `rooms/<room名>/room.json` の `name`/`icon` を書き換える
3. サーバーを再起動する(`systemctl --user restart pocketcrew` など)
4. `/<room名>` を開いて動作を確認する

`_template` はそのまま動く「メモ」room です(一覧+追加フォーム+定時ジョブの見本)。中身の説明は `rooms/_template/README.md` にあります。

### スキルで作る(Claude Code に任せる)

このリポジトリには `.claude/skills/make-room/` が同梱されています。クローンしたフォルダで Claude Code を起動し、「読書記録の部屋を作って」のように話しかけると、`_template` を元に room を作るところまで一気にやってくれます。詳しくは [`.claude/skills/make-room/SKILL.md`](.claude/skills/make-room/SKILL.md)。

## プライバシーと安全性

- 完全に自分の機械の中で動きます。外部の API・クラウドには何も送りません(Claude Code 自体の通信を除く)
- 唯一、機械の外に出る通信はプッシュ通知です。ブラウザの Web Push の仕組み上、通知は Apple(APNs)や Google(FCM)のプッシュサービスを経由します(本文はそのブラウザ・OS の実装に従って暗号化されます)。通知を使わない設定(`config.toml` の `[features] push = false`)にすれば、この経路も無くなります
- `vault` room はあなたが指定したフォルダの外を読めません(`config.toml` の外側パスは弾かれます)
- `config.toml` / `presets.json` / `sessions.json` / `push.json` / `certs/` / `log/` はすべて `.gitignore` 済みです。自分の秘密・個人情報はこれらのファイルにだけ書き、コミットに含めないでください

## ライセンス

MIT License — Copyright (c) 2026 PlugBits。詳細は [`LICENSE`](LICENSE)。

作者: [PlugBits](https://github.com/PlugBits)

---

## English summary

Pocket Crew is a small, self-hosted, phone-first command center for Claude Code. It watches Claude Code sessions running inside tmux and exposes them through a PWA you can add to your phone's home screen: see which sessions are running, send them messages, get push notifications on state changes, and have crashed/restarted sessions auto-restore from a roster file. No Anthropic API key is needed — it drives the Claude Code CLI over tmux, using your existing subscription.

Its standout built-in room is a **vault viewer**: point it at a folder of Markdown notes (e.g. an Obsidian vault) and read/browse them from your phone, with `~/vault/....md`-style links in chat bubbles becoming tap-to-open links.

Features are added as **rooms** — a folder under `rooms/` with a `room.json` plus optional `page.html`/`page.js`, `api.py` (routes), and `jobs.py` (scheduled jobs). A failing room only disables itself; the core server keeps running. See `CLAUDE.md` for the full room contract, and `.claude/skills/make-room/` for a Claude Code skill that scaffolds a new room from a plain-language request.

Requirements: a Claude subscription with Claude Code, tmux, Python 3.11+, and the `cryptography` package (for Web Push). Runs on WSL/Linux (systemd --user unit provided) or Mac (launchd plist provided). Recommended way to reach it from your phone is [Tailscale](https://tailscale.com/), with `tailscale cert` for HTTPS.

License: MIT (Copyright (c) 2026 PlugBits).
