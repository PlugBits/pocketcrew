# room の見本(_template)

これは動く見本です。フォルダ名が `_` で始まるので core は読み込みません(コピーしてから使う)。

## コピーの仕方

```
cp -r rooms/_template rooms/reading
```

コピーしたら書き換えるのは `rooms/reading/room.json` の `name`/`icon`（表示名とアイコン）だけです。

`api.py` と `jobs.py` は room id をフォルダ名から自動で取る（`os.path.basename(...)`）ので、
このまま何もいじらなくても新しい room として動きます。`page.html` の `<script src="/{{ROOM}}.js">`
は配信時に core/rooms.py が room id へ自動で置き換える(段階C)ので書き換え不要です。`page.js` も
自分の `<script src>` から room id を読むので書き換え不要です。

## 各ファイルの役目

- `room.json` — 名前・アイコン・メニューへの出し方（`menu: true` で ⋯メニューに1項目出る。
  `menu` の項目は `href`（別ページに飛ぶ）の代わりに `act`（ホーム画面の `TP.menuActions[act]()`
  を呼ぶ）も書ける）
- `page.html` / `page.js` — `/<room>` で配信されるページ本体。ここでは「メモ」の一覧＋追加フォーム
- `home.css` / `home.js` — room.json の `"home": ["home.css", "home.js"]` を書くと、ホーム画面
  （index.html）に core が差し込む。CSS は `<head>` の直後、JS はホームの本体スクリプトの直後
  （実行済みのあと）。ホーム画面はスタンドアロン PWA で「戻る」が無い1枚のタブなので、room が
  ホームに機能を足す唯一の経路がこれ（別ページに飛ばすと行き止まりになる）。ホームの本体スクリプトは
  IIFE で閉じていて中の変数は見えないので、home.js は自分の DOM・状態を自分で持つ自己完結のスクリプトに
  すること。core とやり取りするのは `window.TP` だけ（`TP.linkifiers` にチャット本文の linkify 関数を
  足す・`TP.menuActions` に上記の `act` ハンドラを登録する・`TP.openBlob(url,title)` で画像/PDF を
  全画面オーバーレイで開く）。実例は `rooms/vault/home.js`。全画面オーバーレイを作るときは
  `class="tp-overlay"` を付ける(スレ→ホームの戻るスワイプがこのクラスで判定している)
- `api.py` — `/api/<room>/...` のハンドラ。`ROUTES = {"GET /": ..., "POST /add": ...}`
- `jobs.py` — 定時ジョブ（`JOBS`）と朝の便りの1段（`BRIEF`）の見本
- 保存先は vault 内の1つの Markdown ファイル（既定 `<room id>/log.md`）。`util.safe_path()` で
  vault の外に出るパスは弾く

## 決まり（core/rooms.py の docstring が本文）

- **room 同士は import しない。** 何かを共有したいときは vault のファイル経由にするか、
  core 側（`core/config.py` や `core/util.py`）に足す。他の room の api.py/jobs.py を
  `import` するのは禁止
- room のフォルダは `sys.path` に足されるので、room 内の補助モジュール（`api.py`/`jobs.py`
  以外の自作 `.py`）は名前が他の room と被らないようにする（先頭に room 名を付けるなど）
- `config.toml` に `[rooms.<room id>]` を足すと room 固有の設定になる:

  ```toml
  [rooms.reading]
  enabled = true          # false で無効化(room.json はそのままにできる)
  file = "reading/log.md" # vault からの相対パス。省略時は "<room id>/log.md"
  ```

- 反映には再起動が要る（`load_all()` は起動時に1回だけ呼ばれる）。ホットリロードは無い

## 動作確認

1. `rooms/<room id>/` を作ったら、サーバを再起動する
2. `/<room id>` を開いて一覧と追加フォームが出るか見る
3. うまく読み込めなかった room は無効化されるだけで core は落ちない。原因は起動ログ、または
   ホーム画面の `room_warnings`（core が `rooms.warnings()` を出す場所）に出る
