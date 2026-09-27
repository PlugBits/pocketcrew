# ポケクル(Pocket Crew) 作業ルール

このファイルは、あなたのクローンで Claude Code が作業するときの手引きです。

## 構成

```
server.py          互換シム。実体は core/server.py(python3 server.py で起動)
core/              サーバー本体。セッション監視・送信・自動復帰・通知・ホーム画面・sw.js・manifest
rooms/             公開の room(機能フォルダ)。_template・vault・workout・plan・daily
rooms-private/     あなた専用の room を置く場所(git 管理外・.gitignore 済み)
config.toml        あなたの設定(config.example.toml をコピーして作る。git 管理外)
presets.json        新しいスレを開くときの初期プロンプト集(presets.example.json をコピーして作る。git 管理外)
.claude/skills/make-room/   room を作るスキル(このファイルの「room の足し方」参照)
```

## 絶対のルール

- **機能を足したいときは core/ を編集しない。room を1つ足す。** core は「セッション監視・送信・通知・ホーム画面の土台」だけを持つ。ワークアウト記録・ダッシュボード・vault ビューアなどは全部 room で、実際に `core/*.py` を触らずに実装できている。あなたが足す機能もそうする
- **秘密・個人情報は config.toml にだけ書く。** コードに直書きしない。パス・ポート・tmux セッション名・vault の場所などはすべて `core/config.py` 経由(`from core import config as C`)で読む
- **room 同士は import しない。** 何かを共有したいときは vault のファイル経由にするか、core 側(`core/config.py`・`core/util.py`)に足す
- room のフォルダは `sys.path` に足されるので、room 内の補助モジュール(`api.py`/`jobs.py` 以外の自作 `.py`)は他の room と名前が被らないようにする(room 名を頭に付けるなど)
- **自分だけの room は `rooms-private/<room id>/` に置く。** ここは `.gitignore` 済みで、公開リポジトリのコミットに含まれない。他の人に配る/共有するつもりの room だけ `rooms/` に置く

## room の契約(room.json とファイル)

room は `rooms/<id>/` または `rooms-private/<id>/` の1フォルダ。フォルダ名が `_` で始まるものは見本用で読み込まれない(`_template` はコピー元)。

必須は `room.json` だけ。他のファイルは全部任意。

- **`room.json`**
  ```json
  {"name": "ワークアウト", "icon": "🏋️", "order": 40,
   "menu": true,
   "tab_in": "plan",
   "home": ["home.css", "home.js"],
   "cache": ["/x"]}
  ```
  - `name`/`icon`/`order`: 表示名・絵文字・並び順(小さいほど先)
  - `menu`: `true` なら⋯メニューに1項目(`/<id>` に飛ぶ)を自動で出す。配列にすると複数項目・独自ラベルを持てる: `[{"label": "🏋️ ワークアウト", "href": "/workout", "order": 40}]`。`href` の代わりに `"act": "vault"` と書くと、ページ遷移せずホーム画面の `TP.menuActions["vault"]()` を呼ぶ(home.js が登録する)
  - `tab_in`: 値に別の room id を書くと、そのページに `tab.js` をタブとして差し込む
  - `home`: `["home.css", "home.js"]` を書くと、ホーム画面(index.html)に差し込まれる。下記参照
  - `cache`: `sw.js`(Service Worker)のキャッシュ対象に足すパス(`page.html`/`page.js`/`home.css`/`home.js` は自動で入るので書かなくてよい)
- **`page.html`** — `/<id>` で配信されるページ本体。`<script src="/{{ROOM}}.js">` の `{{ROOM}}` は配信時に core が room id へ自動置換する(コピーしても書き換え不要)
- **`page.js`** — `/<id>.js` と `/<id>/page.js` で配信。自分の `<script src>` から room id を読み取る作りにしておけば、フォルダをコピーしただけで動く(`_template/page.js` が実例)
- **`tab.js`** — `/<id>/tab.js` で配信。`tab_in` 先のページが読み込む
- **`home.css`/`home.js`** — `/<id>/home.css`・`/<id>/home.js` で配信。`room.json` の `"home"` にあれば、core がホーム画面(index.html)に差し込む: CSS は `<head>` 直後、JS はホーム本体スクリプト(IIFE で閉じている)の閉じタグ直後。ホーム画面は「戻る」の無いスタンドアロン PWA の1枚タブなので、**room がホームに機能を足す唯一の経路がこれ**(別ページに飛ばすと行き止まりになる)。home.js は自分の DOM・状態を自分で持つ自己完結のスクリプトにする。core とやり取りするのは `window.TP` だけ:
  - `TP.linkifiers` — チャット本文の linkify 関数の配列に自分の関数を足せる(例: vault のパスをタップ可能なリンクにする)
  - `TP.menuActions` — `room.json` の `"act"` から呼ばれるハンドラを登録する場所
  - `TP.openBlob(url, title)` — 画像/PDF を全画面オーバーレイで開く
  - 全画面オーバーレイを自分で作るときは `class="tp-overlay"` を付ける(スレ→ホームの戻るスワイプがこのクラスで判定している)
  - 実例: `rooms/vault/home.js`
- **`static/`** — `/<id>/static/<file>` で配信
- **`api.py`** —
  ```python
  ROUTES = {"GET /": get_list, "POST /add": add}
  LEGACY = {"GET /api/plan": "GET /"}   # 旧パスの別名。末尾 * は前方一致
  ```
  `ROUTES` は `/api/<id>/...` に割り当てられる(`"GET /"` → `/api/<id>`)。ハンドラは `fn(req)` の形で、`req.q(name, default)`・`req.body()`・`req.json()` が使える。戻り値は dict/list なら JSON になる。`core.rooms.Resp` を返せば HTML・画像・リダイレクトなど JSON 以外も返せる。`None` を返すと 404
- **`jobs.py`** —
  ```python
  JOBS = [{"name": "brief", "at": "07:30", "fn": fn}, {"name": "x", "every": "minute", "fn": fn}]
  START = [fn]              # 起動時に別スレッドで1回呼ぶ(常駐ワーカー用)
  BRIEF = lambda day: [{"order": 10, "lines": ["## 見出し", "- 本文"], "push": "通知本文"}]
  ```
  `"at"` のジョブは時刻を過ぎている間ずっと毎分呼ばれる(追いつき方式)ので、二重実行しないように `core.rooms.done(name)`/`mark_done(name)` の印(`log/<name>-<day>.done`)を自分で見る。`"weekday": 6` で曜日を限定できる(月=0)。`BRIEF` は朝の便りに足す1段を返す(`order` 順に並ぶ)
- 読み込みに失敗した room は無効になるだけで、core は落ちない(ホーム画面に警告が1行出る。`/api/rooms` の `error` でも見える)

## room 固有の設定

`config.toml` に `[rooms.<id>]` を足すと room ごとの設定になる:

```toml
[rooms.reading]
enabled = true          # false で無効化(room.json はそのままにできる)
file = "reading/log.md" # vault からの相対パス。room 側が room_config() で読む
```

room 側からは `from core import rooms` して `rooms.room_config(room_id)` で読む(`_template/api.py` が実例)。

## room の作り方(まとめ)

1. `cp -r rooms/_template rooms/<id>`(または `rooms-private/<id>`)
2. `room.json` を書き換える
3. 必要なら `page.html`/`page.js`・`api.py`・`jobs.py` を書き換える
4. サーバーを再起動する(`systemctl --user restart pocketcrew` / `launchctl kickstart -k gui/$UID/com.pocketcrew` など。開発中は `python3 server.py` を Ctrl-C → 再実行でもよい)
5. `/api/rooms` を見て、自分の room の `error` が `null` であることを確認する
6. `/<id>` を開いて動作を確認する

詳しい手順・書式・実例(読書記録の部屋)は `.claude/skills/make-room/SKILL.md` にあります。「〇〇の部屋を作って」と話しかければ、このスキルが同じ手順を代行します。

## その他

- vault(Markdown 置き場)の外に出るパスは `core/util.py` の `safe_path()` が弾く。room から vault のファイルを読み書きするときはこれを経由する(`_template/api.py` が実例)
- 触る前に `.bak-*` を取る、置換の前に出現回数を数える、といった一般的な注意はこのプロジェクトにも当てはまります
