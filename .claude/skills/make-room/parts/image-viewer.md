# 部品: 画像の拡大表示

## 何ができるか

サムネイルをタップすると、同じページの中で画像を全画面表示する。新しいタブでは開かない
(ホーム画面に追加した PWA では新しいタブに「閉じる」ボタンが無く、行き止まりになるため)。
閉じるボタン・外側タップ・Escape キーのどれでも閉じられる。

## いつ使う

- `parts/image-gallery.md` でサムネイル一覧を作ったあと、タップして大きく見たいとき
- 「拡大して見たい」「大きく表示したい」と言われたら選ぶ

## 組み込み方

### page.html 側: CSS

全画面オーバーレイには **`tp-overlay` クラスを必ず付ける**。ホーム画面からスレに入ったあと
「左端スワイプで戻る」処理がこのクラスを見て、オーバーレイが開いている間はスワイプ戻りを
無効にする(付け忘れると、拡大表示中に誤ってスワイプで前の画面に戻ってしまう)。

閉じるボタンは右上、48px 以上、`env(safe-area-inset-top)` を足してノッチと被らないように
する。下のヒント文言には **`pointer-events:none` を必ず付ける**(付けないと、ヒント文言の
上でタップしたときに「外側タップで閉じる」が反応せず、文言の下にある要素扱いになって閉じない
という不具合が実際に起きる)。

```css
.mm-viewer{position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.95);display:flex;
  flex-direction:column;align-items:center;justify-content:center;padding:64px 12px 40px}
.mm-viewer img{max-width:100%;max-height:100%;object-fit:contain;border-radius:8px}
.mm-viewer-close{position:absolute;top:calc(10px + env(safe-area-inset-top));right:10px;
  min-height:48px;min-width:48px;padding:0 16px;border-radius:24px;border:0;
  background:rgba(255,255,255,.92);color:#222;font:inherit;font-size:var(--fs-body);font-weight:700}
.mm-viewer-hint{position:absolute;bottom:calc(12px + env(safe-area-inset-bottom));left:0;right:0;
  text-align:center;color:rgba(255,255,255,.8);font-size:var(--fs-sub);pointer-events:none}
```

### page.js 側

```js
function openViewer(images, i) {
  if (!images || !images[i]) return;
  closeViewer();
  const ov = document.createElement('div');
  ov.className = 'tp-overlay mm-viewer';   // tp-overlay は必ず付ける(ホームのスワイプ戻り判定用)
  ov.id = 'mm-viewer';
  ov.setAttribute('role', 'dialog');
  ov.setAttribute('aria-label', (i + 1) + '枚目の画像');
  ov.innerHTML = `
    <button class="mm-viewer-close" id="mm-viewer-close" aria-label="閉じる">✕ 閉じる</button>
    <img src="/api/img?p=${encodeURIComponent(images[i])}" alt="${i + 1}枚目">
    <div class="mm-viewer-hint">長押しで保存 ・ 外側をタップで閉じる</div>`;
  ov.addEventListener('click', (e) => { if (e.target === ov) closeViewer(); });
  document.body.appendChild(ov);
  document.getElementById('mm-viewer-close').addEventListener('click', closeViewer);
}

function closeViewer() {
  const ov = document.getElementById('mm-viewer');
  if (ov) ov.remove();
}

document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeViewer(); });

// 呼び出し側の配線の例(サムネイルに data-i を振っておく)
document.querySelectorAll('img.thumb').forEach((im) =>
  im.addEventListener('click', () => openViewer(currentImages, +im.dataset.i)));
```

画像自体は `<img>` のままなので、拡大表示の中でも長押しでの保存はそのまま使える(オーバー
レイにしても `image-gallery.md` の「`<a>` で包まない」ルールは変わらない)。

## 確認のしかた

390px 幅の画面で:

- サムネイルをタップすると、ページ遷移(URLが変わる・戻るボタンが出る)ではなく、同じ画面の
  上に画像が全画面で出るか
- 閉じるボタンがノッチ・角丸に隠れず、指で押せる大きさで右上にあるか
- 画像の外側(黒い余白部分)をタップすると閉じるか。特に**下のヒント文言の上をタップしても
  閉じる**か(閉じない場合は `pointer-events:none` が抜けている)
- 拡大表示中に画面外周から右へスワイプしても、司令室に戻らず何も起きないか(`tp-overlay`
  クラスの効果)
- 拡大表示中でも画像を長押しして保存できるか

## つまずき

- **`tp-overlay` クラスを付け忘れる**: 拡大表示中に左端スワイプすると、ホームへ戻る処理が
  発火してしまう。見た目は正しくても閉じるはずのタイミングで思わぬ画面遷移が起きる
- **ヒント文言に `pointer-events:none` を付け忘れる**: 「外側タップで閉じる」の判定が
  `e.target === ov` になっているため、ヒント文言(別の要素)の上をタップすると `e.target`
  がヒント文言になり、閉じる条件に一致しなくなる。実際に起きた不具合なので必ず付ける
- **新しいタブで開いてしまう**: `target="_blank"` や `window.open` を使うと、ホーム画面に
  追加した PWA では閉じるボタンの無い行き止まりになる。必ず同じページの中のオーバーレイにする
- **閉じるボタンが小さい/ノッチに隠れる**: 48px 未満にしない。`env(safe-area-inset-top)` を
  足し忘れない
