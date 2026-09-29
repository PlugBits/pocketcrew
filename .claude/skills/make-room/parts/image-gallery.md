# 部品: 画像の一覧+保存

## 何ができるか

画像のサムネイル一覧を出し、1枚ずつは長押しで端末に保存、複数枚は「まとめて保存」ボタンで
一括保存できるようにする。

## いつ使う

- room が扱うデータに画像が添付されていて、「画像を保存したい」「画像を端末に持っていきたい」
  という要求があるとき
- ユーザーが「画像を保存したい」「まとめて保存」と言ったら、聞き返さずにこの部品を選んでよい

## 組み込み方

### api.py 側: 画像パスを返す

room の API は画像そのものではなく、vault からの相対パスの一覧を返す。画像そのものの配信は
core が持つ `/api/img?p=<vault相対パス>` に任せる(下記参照)。ファイル名の候補が複数ある
(生成物と手動アップロードなど)場合は、存在するものを優先順で拾う:

```python
def _find_images(dir_path, vault_root, max_n=3):
    """dir_path の中から、存在する画像を優先順で拾って vault 相対パスのリストにする。
    例: 1枚目は "1.png" を優先し、無ければ "gen-1.jpg" を使う、という決め方。"""
    out = []
    for n in range(1, max_n + 1):
        for fname in (f"{n}.png", f"gen-{n}.jpg"):
            p = os.path.join(dir_path, fname)
            if os.path.isfile(p):
                out.append(os.path.relpath(p, vault_root))
                break
    return out
```

この `images` のリストを、一覧や詳細の JSON レスポンスに含めて返す(例:
`{"ok": True, "images": ["reading/2026-09-01/1.png"]}`)。

画像そのものは core の `/api/img?p=<vault相対パス>` が配信する(`core/server.py` の
`api_img()`)。`util.safe_path()` で vault の外・隠しファイルは弾かれ、拡張子から
Content-Type を決め、一定サイズを超えるものは断る。room 側で画像配信を自前で書く必要は無い。

### page.html 側: サムネイルの並べ方(重要な制約あり)

サムネイルは **`<a>` で包まない**。iOS では画像を `<a>` の中に置くと、長押ししたときに
リンクのメニュー(「リンクを開く」など)が出てしまい、画像保存のメニューが出にくくなる。
`<img>` を直接並べるだけで、長押し→保存がブラウザ標準の動きとして使える。

同じ理由で、サムネイルには次を **付けない**:

- `-webkit-touch-callout:none`(長押しメニュー自体を殺してしまう)
- `user-select:none` / `pointer-events:none`(長押し・保存を妨げる)
- `draggable="false"`
- 見た目のための CSS 背景画像や blob URL 化(実体の `<img src>` である必要がある)

```css
#mm-root .thumbs{display:flex;gap:8px;flex-wrap:wrap;margin:0 2px 8px}
#mm-root .thumbs img.thumb{display:block;width:96px;height:96px;object-fit:cover;
  border-radius:10px;border:1px solid var(--line);cursor:zoom-in}
#mm-root .saveall{display:block;width:100%;margin:8px 0 4px;min-height:48px}
```

```html
<div class="thumbs">
  <img class="thumb" data-i="0" src="/api/img?p=reading%2F2026-09-01%2F1.png" alt="1枚目">
  <img class="thumb" data-i="1" src="/api/img?p=reading%2F2026-09-01%2F2.png" alt="2枚目">
</div>
<button class="saveall" id="mm-save-all" disabled>画像2枚をまとめて保存</button>
<div class="hint">画像を長押しでも1枚ずつ保存できます</div>
```

タップして拡大表示したい場合は `parts/image-viewer.md` を合わせて使う(サムネイルの
`click` イベントで開く)。

### page.js 側: まとめて保存(共有シート)

`navigator.share({ files })` を使う。**この API はユーザー操作(タップ)の直後でないと
弾かれる**ので、`await fetch(...)` を挟んでから `share()` を呼ぶと(特に iOS で)失敗する。
そのため、詳細画面を開いた時点で先に画像を `File` にしておき、準備できたらボタンを押せる
ようにする(ボタンは準備が終わるまで `disabled`)。`https`(セキュアコンテキスト)でないと
そもそも使えないので、`navigator.canShare` で確認し、使えない環境ではボタンの文言を
「この画面ではまとめて保存できません(長押しで保存)」に変えて諦める。

```js
let shareFiles = null;

async function prepareShare(images, dirLabel, btn) {
  shareFiles = null;
  try {
    const files = await Promise.all(images.map(async (p) => {
      const r = await fetch('/api/img?p=' + encodeURIComponent(p));
      if (!r.ok) throw new Error(r.status);
      const blob = await r.blob();
      return new File([blob], dirLabel + '-' + p.split('/').pop(), { type: blob.type || 'image/png' });
    }));
    if (!btn.isConnected) return;   // 読んでいる間に画面が切り替わった
    if (!(navigator.canShare && navigator.canShare({ files }))) {
      btn.textContent = 'この画面ではまとめて保存できません(長押しで保存)';
      return;
    }
    shareFiles = files;
    btn.disabled = false;
    btn.addEventListener('click', async () => {
      try {
        await navigator.share({ files: shareFiles });
      } catch (e) {
        if (e && e.name === 'AbortError') return;   // シートを閉じただけ(何もしない)
        btn.textContent = '保存できませんでした(長押しで保存してください)';
      }
    });
  } catch (e) {
    btn.textContent = '画像を読めませんでした';
  }
}
```

## 確認のしかた

390px 幅の画面で:

- サムネイルが折り返して並び、横スクロールが出ないか
- サムネイルを長押しすると、ブラウザ標準の「画像を保存」メニューが出るか(リンクのメニュー
  になっていたら `<a>` で包んでしまっている)
- 「まとめて保存」ボタンが、開いた直後は無効(グレー)で、少ししてから押せるようになるか
- 実際に押して共有シートが出て、画像を保存できるか(https 環境で確認する。http だとそもそも
  ボタンの文言が「まとめて保存できません」になっているはず)
- シートを開いて何もせず閉じても、エラー表示が出ないか(AbortError は無視する仕様)

## つまずき

- **サムネイルを `<a>` で包んでしまう**: 長押しがリンクメニューになり、画像保存がしにくく
  なる。包まず `<img>` を直接置く
- **`await fetch` の後に `share()` を呼んで弾かれる**: iOS はユーザー操作から離れた
  `share()` 呼び出しを拒否する。画像は詳細を開いた時点で先読みしておき、`share()` 自体は
  クリックハンドラの中で(すでに用意済みの `File` を使って)即座に呼ぶ
- **http では動かない**: `navigator.share`/`canShare` はセキュアコンテキスト限定。開発中に
  「動かない」と思ったら、まず https で試しているか確認する
- **`canShare` を確認せず `share()` を呼ぶ**: 環境によっては `share` 自体はあっても
  `files` 付きの共有に対応していないことがある。`canShare({files})` で先に確認し、ダメなら
  ボタンの文言を変えて諦める(エラーを投げっぱなしにしない)
