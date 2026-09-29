# 部品: 一覧→詳細(1ページ内)

## 何ができるか

API から取った項目の一覧を出し、1件タップするとページ遷移せずに同じページの中で詳細を表示
する。詳細には「← 一覧」で戻るボタンを置く。一覧には任意で「今日」「明日」のバッジを付け、
今日→明日→それ以外は新しい順、の並びにできる。

## いつ使う

- room が扱うデータが「複数件あって、1件ずつ中身を見たい」形のとき(投稿・記録・メモの束など)
- 日付を持つデータで「今日の分・明日の分をまず見たい」という要求があるとき(バッジ+並び順)

## 組み込み方

### api.py 側: 一覧のフォルダ名検証と並び順

データが「日付-名前」のようなフォルダ単位で vault に置かれている場合、フォルダ名は
**厳密な正規表現**で検証してから `util.safe_path()` に渡す(2段構えにする)。

```python
import datetime as dt
import re

from core import util

# フォルダ名の形。日付8桁のプレフィックスの後ろは英数字と . _ - のみ(スラッシュや
# 隠しファイル名(. で始まる)は入らない)。util.safe_path() の隠しファイル拒否とあわせて二重に守る。
ITEM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[A-Za-z0-9._-]+$")
_DATE_SPLIT_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")


def _item_dir(base_dir, name):
    """name(フォルダ名)が正しい形で、実在するフォルダなら絶対パスを返す。それ以外は None"""
    if not ITEM_RE.match(name or ""):
        return None
    full = util.safe_path(f"{base_dir}/{name}")
    if not full or not os.path.isdir(full):
        return None
    return full


def get_list(req, base_dir):
    """今日→明日→残りは日付降順、同日はフォルダ名順に並べた一覧を返す"""
    today = dt.date.today()
    tomorrow = today + dt.timedelta(days=1)
    base = util.safe_path(base_dir)
    items = []
    if base and os.path.isdir(base):
        for name in os.listdir(base):
            m = ITEM_RE.match(name)
            if not m or not os.path.isdir(os.path.join(base, name)):
                continue
            dm = _DATE_SPLIT_RE.match(name)
            d = dt.date.fromisoformat(dm.group(1))
            when = "today" if d == today else ("tomorrow" if d == tomorrow else "")
            items.append({"dir": name, "date": dm.group(1), "name": dm.group(2), "when": when, "_d": d})
    order = {"today": 0, "tomorrow": 1}
    items.sort(key=lambda p: (order.get(p["when"], 2), -p["_d"].toordinal(), p["dir"]))
    for p in items:
        del p["_d"]
    return {"ok": True, "items": items}
```

`when` はサーバー側で計算して返す(page.js 側では「今日かどうか」を判定し直さない)。

### page.html 側: CSS

一覧の行・バッジ・詳細の戻るボタンは `_template` の配色変数を使う。戻るボタンは 48px 以上。

```css
#mm-root .row{display:flex;align-items:baseline;gap:8px;width:100%;text-align:left;
  background:var(--card);color:var(--fg);border:1px solid var(--line);border-bottom:0;
  padding:13px 14px;font-size:var(--fs-body);font-family:inherit;min-height:48px}
#mm-root .row:first-of-type{border-radius:12px 12px 0 0}
#mm-root .row:last-of-type{border-bottom:1px solid var(--line);border-radius:0 0 12px 12px}
#mm-root .row:only-of-type{border-radius:12px}
#mm-root .row .dt{flex:none;color:var(--dim);font-size:var(--fs-sub)}
#mm-root .row .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#mm-root .row .badge{flex:none;font-size:var(--fs-sub);color:var(--acc);border:1px solid var(--acc);
  border-radius:8px;padding:1px 7px}
#mm-root #mm-detail{display:none}
#mm-root #mm-detail.on{display:block}
#mm-root #mm-list.off{display:none}
#mm-root .dtop{display:flex;align-items:center;gap:10px;margin:2px 2px 12px}
#mm-root .dtop button.back{background:none;border:0;color:var(--acc);font-size:var(--fs-body);
  padding:8px 4px;min-height:48px;min-width:48px;font-family:inherit}
#mm-root .dtop h2{font-size:var(--fs-body);margin:0;font-weight:600;flex:1;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
```

```html
<div id="mm-list"></div>
<div id="mm-detail"></div>
```

### page.js 側

```js
const badgeLabel = { today: '今日', tomorrow: '明日' };

function renderList(items) {
  const listEl = document.getElementById('mm-list');
  listEl.innerHTML = items.length
    ? items.map((it) => `
      <button class="row" data-d="${esc(it.dir)}">
        <span class="dt">${esc(it.date)}</span>
        <span class="nm">${esc(it.name)}</span>
        ${it.when && badgeLabel[it.when] ? `<span class="badge">${badgeLabel[it.when]}</span>` : ''}
      </button>`).join('')
    : '<div class="none">まだ何もありません</div>';
  listEl.querySelectorAll('.row').forEach((b) =>
    b.addEventListener('click', () => openDetail(b.dataset.d)));
}

function openDetail(dir) {
  // ここで詳細用の fetch をして renderDetail(doc) を呼ぶ(部品固有ではないので省略)
  document.getElementById('mm-list').classList.add('off');
  document.getElementById('mm-detail').classList.add('on');
}

function closeDetail() {
  document.getElementById('mm-detail').classList.remove('on');
  document.getElementById('mm-list').classList.remove('off');
}

function renderDetail(doc) {
  document.getElementById('mm-detail').innerHTML = `
    <div class="dtop"><button class="back" id="mm-back">← 一覧</button><h2>${esc(doc.name)}</h2></div>
    <!-- ここに詳細の中身 -->`;
  document.getElementById('mm-back').addEventListener('click', closeDetail);
}
```

## 確認のしかた

390px 幅の画面で:

- 一覧の各行が指で押せる高さ(48px 以上)で、テキストが長くても行がはみ出さず省略記号
  (`...`)になるか
- 「今日」「明日」バッジがある場合、並び順が今日→明日→それ以外(新しい順)になっているか
- 行をタップすると URL が変わらずに詳細が表示され、「← 一覧」で確実に一覧へ戻れるか
- 存在しない/不正なフォルダ名を直接 URL やパラメータで渡しても、詳細が開かずエラーとして
  扱われるか(サーバー側の正規表現+`safe_path` の二重チェックが効いているか)

## つまずき

- **フォルダ名の検証を1段だけにする**: 正規表現だけだと巧妙な名前をすり抜ける余地があり、
  `safe_path()` だけだと想定外の形式のフォルダまで拾ってしまう。両方を通す
- **`when`(今日/明日の判定)をクライアント側でやり直す**: 端末のタイムゾーンや時計のずれで
  サーバーとクライアントの「今日」がずれることがある。判定はサーバー側の1箇所に寄せる
- **詳細を開いたまま一覧を更新すると表示が壊れる**: 一覧の再取得は詳細を閉じてから行う
  (開いたまま裏で差し替えると、閉じたときの見た目が一瞬おかしくなることがある)
- **戻るボタンが小さい/長いタイトルでレイアウトが崩れる**: `.dtop h2` に
  `overflow:hidden;text-overflow:ellipsis;white-space:nowrap` を付けて、戻るボタンの幅は
  固定(48px 以上)を保つ
