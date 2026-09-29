---
name: make-room
description: ポケクル(Pocket Crew)に新しい room(機能のフォルダ1つ)を作る。「〇〇の部屋を作って」「room を作って」「reading room を追加して」のように言われたら使う。rooms/_template を元に room.json・page.html/page.js・(必要なら)api.py/jobs.py を作り、再起動して /api/rooms と /<room id> で動作確認するところまで行う。
---

# room を作る

ポケクル(Pocket Crew)の room は `rooms/<id>/`(または `rooms-private/<id>/`)の1フォルダです。`room.json` さえあれば room として認識され、`page.html`/`page.js`/`api.py`/`jobs.py` はすべて任意です。room 契約の全体像は `CLAUDE.md` を参照してください(この手順はその要約+実行手順です)。

## 手順

### 1. room id と表示名を決める(または聞く)

- id は英数字とハイフン/アンダースコアのみ、他の room・`rooms/`・`rooms-private/` の両方と被らない名前にする(例: `reading`)
- 表示名(`name`)とアイコン(絵文字1つ、`icon`)を決める。ユーザーが「読書記録の部屋を作って」とだけ言ったら、id は `reading`、name は「読書記録」、icon は 📚 のように自分で妥当な値を決めてよい(いちいち聞き返さない)

### 2. 公開するか、自分専用かを決める

- 「みんなに配る room」「サンプルにしたい」なら `rooms/<id>/`
- 「自分だけの記録」「個人的な内容」なら `rooms-private/<id>/`(git 管理外・公開リポジトリに乗らない)
- 迷ったら、または明言が無ければ `rooms-private/<id>/` を選ぶ(あとから `rooms/` に `mv` すればよいだけなので、安全な側に倒す)

### 3. 部品を選ぶ

`.claude/skills/make-room/parts/` には、よく使う画面パーツが1つ1ファイルで置いてある。
room の要件に合いそうなものがあれば、AskUserQuestion で確認してから使う(自分で決め打ちで
入れない。ただし下記の「聞かずに決めてよい場合」は例外)。

- `parts/copy-buttons.md` — テキストをコピーするボタン(本文/タグを分けて別々にコピー、など)
- `parts/image-gallery.md` — 画像の一覧+長押し保存+まとめて保存
- `parts/image-viewer.md` — サムネイルをタップしたときの全画面拡大表示(`image-gallery` とセットで使うことが多い)
- `parts/list-detail.md` — 一覧→詳細を同じページ内で(「今日」「明日」バッジ+並び替え込み)

**聞き方のルール(重要)**:

- この司令室は AskUserQuestion を出しても**電話の画面には1問目しか映らない**。1回の
  AskUserQuestion 呼び出しの `questions` 配列には**必ず1問だけ**入れる。複数の部品をまとめて
  1回で聞かない(必ず部品ごとに呼び出しを分ける)
- 聞く順番は固定でよい: ① `list-detail`(一覧+詳細にする?)→ ② `copy-buttons`(コピー
  ボタンを付ける?)→ ③ `image-gallery`(画像の保存を付ける?)→ ④ `image-viewer`
  (画像をタップで拡大表示できるようにする?。③ が「いいえ」なら聞かずに「いいえ」にする)
- 各質問は「〇〇を付けますか?」のような、はい/いいえで答えられる形にする
- **ユーザーの要望からすでに答えが明らかな部品は聞かずに決める**。例:「画像を保存したい」
  と言われたら `image-gallery` は聞かずに「はい」。「一覧から選んで開きたい」なら
  `list-detail` は聞かずに「はい」。「コピペしたい」なら `copy-buttons` は聞かずに「はい」。
  要望に出てこない部品だけ質問する
- ユーザーが「おまかせ」と言った場合は、どの部品も聞かずに、要件から妥当な組み合わせを自分で
  決めてよい(読書記録のような単純な記録ものなら基本は部品なし、投稿文の貼り付けのような
  ものなら `copy-buttons`、画像つきの記録なら `image-gallery`+`image-viewer`、など)
- 選び終えたら、確認や質問を重ねずに「これで作ります: 一覧+詳細・コピーボタン」のように
  **選んだ部品を1行で言ってから**、そのまま次の手順(`_template` のコピー)に進む。選んだ
  部品が無ければ「部品はなしで作ります」のように1行で言う

各部品の組み込み方(api.py 側・page.html の CSS・page.js のコード・確認のしかた・つまずき)
は、それぞれの `parts/*.md` に書いてある。コピペで使える完成形のコードなので、そのまま
`_template` の該当箇所に足せばよい。

### 4. `_template` をコピーする

```sh
cp -r rooms/_template rooms-private/<id>
rm rooms-private/<id>/README.md   # 雛形の説明書。新しい room には要らない
```

(公開する場合は `rooms/<id>`)

### 5. `room.json` を書き換える

`name`/`icon`/`order` を決めた値に。`menu` は「⋯メニューに出すか」で、シンプルな1項目なら `true` のままでよい。

### 6. `page.html`/`page.js`/`api.py`/`jobs.py` を要件に合わせて書き換える

`_template` はそのまま「1行メモ帳」として動く(一覧+追加フォーム)。多くの「記録する系」の room はこの形の変形で足りる。保存先は vault 内の1つの Markdown ファイル(既定 `<id>/log.md`。`util.safe_path()` で vault の外に出るパスは弾かれる)。

具体的な書き方は下の「worked example」を型として使う。

### 7. データの置き場を決める

vault 配下の相対パス(`config.toml` の `[paths] vault` が指すフォルダからの相対パス)にする。雛形の既定は `<room id>/log.md`。ファイル名を変えたいときは、`api.py` の既定値を書き換えるか(下の読書記録の例は `books.md` にしている)、`config.toml` で上書きする:

```toml
[rooms.<id>]
file = "reading/books.md"
```

### 8. 再起動して確認する

```sh
systemctl --user restart pocketcrew   # 環境によっては launchctl kickstart -k gui/$UID/com.pocketcrew、または python3 server.py の再起動
curl -s http://127.0.0.1:8787/api/rooms | python3 -m json.tool
```

自分の room の `"error"` が `null` であることを確認する(`null` 以外ならエラーメッセージが入っているので、それを読んで直す)。問題なければブラウザ/スマホで `/<id>` を開き、一覧と追加フォームが出ることを確かめる。部品を使った場合は、選んだ部品ごとに `parts/<部品名>.md` の「確認のしかた」も1つずつ見る。

### どの room にも効く決まり

部品を使う/使わないに関わらず、すべての room に共通で当てはまる決まり:

- タップ対象(ボタン・行・リンク)は最低 48px 四方にする
- 390px 幅で横スクロールが出ないようにする(はみ出す要素が無いか確認する)
- 「できた」と言う前に、必ず 390px 幅の画面(スマホ相当)で見てから言う
- コード(`page.html`/`page.js`/`api.py`/`jobs.py`)を変えたら、確認の前に必ず再起動する(ホットリロードは無いので、変更前の内容のまま確認してしまう事故を防ぐ)

### よくあるつまずき

- **room が⋯メニューやホームに出ない・404 になる**: まず `/api/rooms` を見る。読み込みに失敗した room は**その room だけ**無効になり、core 自体は落ちない。`error` に理由(多くは Python の構文エラーか、`room.json` の JSON が壊れている)が入っている
- **設定を変えたのに反映されない**: room の読み込み(`load_all()`)は起動時に1回だけ。設定・コードを変えたら必ず再起動する(ホットリロードは無い)
- **`room.json` が正しい JSON か**: 末尾カンマ・引用符の閉じ忘れに注意(JSON であって JS オブジェクトではない)
- **他の room の api.py/jobs.py を import している**: 禁止(room 同士は import しない)。共有したいものは vault ファイル経由にするか core 側に足す
- **保存先が vault の外を指している**: `util.safe_path()` が `None` を返して 403/エラーになる。`config.toml` の `file` 設定を確認する

---

## worked example: 「読書記録の部屋」

「読書記録の部屋を作って」と言われたときの、実際に動くファイル一式です。id は `reading`、保存先は `~/vault/reading/books.md`(1行1冊、`- YYYY-MM-DD タイトル / 著者 / 状態` の書式)。

### `rooms-private/reading/room.json`

```json
{"name": "読書記録", "icon": "📚", "order": 100, "menu": true}
```

### `rooms-private/reading/api.py`

```python
"""読書記録の API。

  GET  /api/reading       一覧を返す({"items": [...]})。新しい行が先頭
  POST /api/reading/add   1冊追記する({"title": "...", "author": "...", "status": "..."})

保存先は vault 内の1つの Markdown ファイル。config.toml の [rooms.reading] file で変えられる
(既定は "reading/books.md")。room id はフォルダ名から自動で取る。
"""
import os
import time

from core import rooms
from core import util

_ROOM_ID = os.path.basename(os.path.dirname(os.path.abspath(__file__)))


def _file_path():
    rel = rooms.room_config(_ROOM_ID).get("file", f"{_ROOM_ID}/books.md")
    return util.safe_path(rel)


def get_list(req):
    path = _file_path()
    if not path or not os.path.isfile(path):
        return {"items": []}
    with open(path, encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]
    lines.reverse()
    return {"items": lines}


def add(req):
    body = req.json()
    title = str(body.get("title") or "").strip()
    author = str(body.get("author") or "").strip()
    status = str(body.get("status") or "読書中").strip()
    if not title:
        return {"ok": False, "error": "title が空です"}
    path = _file_path()
    if not path:
        return {"ok": False, "error": "保存先が不正です(config.toml の file 設定を確認)"}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    stamp = time.strftime("%Y-%m-%d")
    line = f"- {stamp} {title}" + (f" / {author}" if author else "") + f" / {status}"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    util.invalidate_status()
    return {"ok": True}


ROUTES = {"GET /": get_list, "POST /add": add}
```

### `rooms-private/reading/page.html`

`_template/page.html` の配色変数(`:root`)と左端スワイプの処理をそのまま残し、`#mm-root` の中を読書記録用のフォームに変えた完成形です。このまま保存すれば動きます(`{{ROOM}}` はサーバーが room id に置き換えます)。

```html
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="theme-color" content="#070a14">
<title>ポケクル · 読書記録</title>
<style>
  /* :root の配色変数は rooms/_template/page.html と同じものをコピーする(ダークテーマ1本) */
  :root{--bg:#070a14;--fg:#e8ecf5;--sub:#a9b3cc;--dim:#8892b0;--card:#0e1326;--line:#1b2340;--warn:#ff6b7a;--acc:#5aa0ff;
    --fs-body:16px;--fs-sub:13px;--fs-title:18px;--lh:1.6;
    --font-ui:-apple-system,BlinkMacSystemFont,'Hiragino Sans','Noto Sans JP',sans-serif;}
  html,body{margin:0;background:var(--bg);color:var(--fg);font-family:var(--font-ui);font-size:var(--fs-body);line-height:var(--lh);-webkit-text-size-adjust:100%}
  #mm-root{padding:calc(10px + env(safe-area-inset-top)) 12px calc(30px + env(safe-area-inset-bottom))}
  #mm-root .top{display:flex;align-items:center;gap:10px;margin:4px 2px 14px}
  #mm-root .top a{color:var(--acc);text-decoration:none;font-size:var(--fs-body);flex:none}
  #mm-root .top h1{font-size:var(--fs-title);margin:0;font-weight:600;flex:1}
  #mm-root .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin-bottom:12px}
  #mm-root .row{display:flex;gap:8px;margin-bottom:8px}
  #mm-root .row:last-child{margin-bottom:0}
  #mm-root input[type=text],#mm-root select{flex:1;min-width:0;box-sizing:border-box;background:#0b1020;color:var(--fg);border:1px solid var(--line);border-radius:10px;padding:10px;font-size:16px;min-height:44px}
  #mm-root button{background:#1f2f5e;color:#dfe7ff;border:1px solid #2c3f7a;border-radius:10px;padding:10px 14px;font-size:var(--fs-body);min-height:44px;flex:none}
  #mm-root button:disabled{opacity:.4}
  #mm-root .item{padding:9px 0;border-bottom:1px solid var(--line);font-size:var(--fs-body);white-space:pre-wrap;word-break:break-word}
  #mm-root .item:last-child{border-bottom:0}
  #mm-root .none{color:var(--sub);font-size:var(--fs-sub);padding:10px 2px}
  #mm-root .err{color:var(--warn);font-size:var(--fs-sub);margin-top:8px;display:none}
</style>
</head>
<body>
<div id="mm-root">
  <div class="top">
    <a href="/" onclick="location.replace('/');return false">← 司令室</a>
    <h1>読書記録</h1>
  </div>
  <div class="card">
    <div class="row"><input type="text" id="rd-title" placeholder="タイトル" maxlength="200"></div>
    <div class="row"><input type="text" id="rd-author" placeholder="著者(任意)" maxlength="200"></div>
    <div class="row">
      <select id="rd-status"><option>読書中</option><option>読了</option><option>積読</option></select>
      <button id="rd-add">追加</button>
    </div>
    <div class="err" id="rd-err"></div>
  </div>
  <div class="card"><div id="rd-list"></div></div>
</div>
<!-- {{ROOM}} は配信時に core/rooms.py が room id に置き換える。左端スワイプで司令室へ戻るスクリプトは
     _template/page.html からそのままコピー -->
<script>
(function(){
  var sx=0,sy=0,st=0,on=false,drag=false;
  document.addEventListener('touchstart',function(e){
    var t=e.touches[0]; on=e.touches.length===1&&t.clientX<28; drag=false;
    if(on){sx=t.clientX;sy=t.clientY;st=Date.now();}
  },{passive:true});
  document.addEventListener('touchmove',function(e){
    if(!on) return; var t=e.touches[0], dx=t.clientX-sx, dy=t.clientY-sy;
    if(!drag){ if(Math.abs(dy)>12&&Math.abs(dy)>Math.abs(dx)){on=false;return;} if(dx>10) drag=true; else return; }
    e.preventDefault(); document.body.style.transition='none'; document.body.style.transform='translateX('+Math.max(0,dx)+'px)';
  },{passive:false});
  document.addEventListener('touchend',function(e){
    if(!on) return; on=false; if(!drag) return;
    var t=e.changedTouches[0], dx=t.clientX-sx, v=dx/Math.max(1,Date.now()-st);
    var go=dx>innerWidth/3||(v>0.5&&dx>40);
    document.body.style.transition='transform .2s';
    document.body.style.transform=go?'translateX(100%)':'';
    if(go) setTimeout(function(){location.replace('/');},180);
  },{passive:true});
  document.addEventListener('touchcancel',function(){ if(on&&drag){document.body.style.transition='transform .2s';document.body.style.transform='';} on=false; },{passive:true});
  addEventListener('pageshow',function(){document.body.style.transition='';document.body.style.transform='';});
})();
</script>
<script src="/{{ROOM}}.js"></script>
</body>
</html>
```

### `rooms-private/reading/page.js`

```js
(() => {
  const ROOM = (() => {
    try {
      const src = document.currentScript.src;
      const m = src.match(/\/([^/?]+?)(?:\/page)?\.js(?:\?|$)/);
      if (m) return m[1];
    } catch (e) {}
    return location.pathname.replace(/^\//, '') || 'reading';
  })();
  const API = `/api/${ROOM}`;

  const listEl = document.getElementById('rd-list');
  const titleEl = document.getElementById('rd-title');
  const authorEl = document.getElementById('rd-author');
  const statusEl = document.getElementById('rd-status');
  const addBtn = document.getElementById('rd-add');
  const errEl = document.getElementById('rd-err');

  function esc(s) { return String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])); }

  async function load() {
    const r = await fetch(API, { cache: 'no-store' });
    const j = await r.json();
    const items = j.items || [];
    listEl.innerHTML = items.length
      ? items.map(t => `<div class="item">${esc(t)}</div>`).join('')
      : '<div class="none">まだ何もありません</div>';
  }

  async function add() {
    const title = titleEl.value.trim();
    if (!title) return;
    addBtn.disabled = true;
    errEl.style.display = 'none';
    try {
      const r = await fetch(API + '/add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, author: authorEl.value.trim(), status: statusEl.value }),
      });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || '失敗しました');
      titleEl.value = ''; authorEl.value = '';
      await load();
    } catch (e) {
      errEl.textContent = '追加できませんでした: ' + e.message;
      errEl.style.display = 'block';
    } finally {
      addBtn.disabled = false;
    }
  }

  addBtn.addEventListener('click', add);
  load();
})();
```

### `rooms-private/reading/jobs.py`(任意。朝の便りに1段足す例)

```python
import os
import time

from core import rooms
from core import util

_ROOM_ID = os.path.basename(os.path.dirname(os.path.abspath(__file__)))


def _brief(day):
    rel = rooms.room_config(_ROOM_ID).get("file", f"{_ROOM_ID}/books.md")
    path = util.safe_path(rel)
    count = 0
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            count = sum(1 for line in f if line.startswith(f"- {day}"))
    if count == 0:
        return []
    return [{"order": 60, "lines": ["## 読書記録", f"- 今日の追加: {count}件"]}]


JOBS = []       # 定時ジョブが要らなければ空でよい
BRIEF = _brief
```

### 動作確認

```sh
systemctl --user restart pocketcrew
curl -s http://127.0.0.1:8787/api/rooms | python3 -m json.tool | grep -A5 '"reading"'
```

`"error": null` を確認したら、`/reading` を開いてタイトルを1件追加し、一覧に出るか見る。`~/vault/reading/books.md` にも行が増えているはず。部品を足した room を作ったときは、ここで選んだ部品ごとに `parts/<部品名>.md` の「確認のしかた」を1つずつ実際にやってから「できた」と言う(例: `image-gallery` を選んだなら、まとめて保存ボタンが実際に共有シートを開くかまで確かめる)。
