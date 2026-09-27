# deploy/

常駐させるための雛形2つ。詳しい手順は [../README.md](../README.md) の「導入」を見てください。ここではファイルの中身だけ説明します。

## WSL / Linux — `pocketcrew.service`(systemd --user)

`%h` は systemd がホームディレクトリに展開するので、書き換え不要でそのまま使えます(クローンした場所が `~/pocketcrew` である前提)。別の場所に置いた場合は `WorkingDirectory` と `ExecStart` のパスを書き換えてください。

```sh
mkdir -p ~/.config/systemd/user
cp deploy/pocketcrew.service ~/.config/systemd/user/pocketcrew.service
systemctl --user daemon-reload
systemctl --user enable --now pocketcrew
systemctl --user status pocketcrew
```

ログイン時に自動起動しない場合(WSL など)は `loginctl enable-linger $USER` を1回実行してください。

設定を変えたあとの反映:

```sh
systemctl --user restart pocketcrew
journalctl --user -u pocketcrew -f    # ログを見る
```

## Mac — `com.pocketcrew.plist`(launchd)

`/PATH/TO/pocketcrew` を実際にクローンしたパス(例: `/Users/yourname/pocketcrew`)に書き換えてから使います。

```sh
sed -i '' 's#/PATH/TO/pocketcrew#/Users/yourname/pocketcrew#g' deploy/com.pocketcrew.plist
cp deploy/com.pocketcrew.plist ~/Library/LaunchAgents/com.pocketcrew.plist
launchctl load ~/Library/LaunchAgents/com.pocketcrew.plist
```

設定を変えたあとの反映:

```sh
launchctl unload ~/Library/LaunchAgents/com.pocketcrew.plist
launchctl load ~/Library/LaunchAgents/com.pocketcrew.plist
```

どちらも `server.py`(リポジトリ直下)を起動するだけで、実体は `core/server.py` です。Python 3.11 以上が必要です(`tomllib` を標準ライブラリで使うため)。
