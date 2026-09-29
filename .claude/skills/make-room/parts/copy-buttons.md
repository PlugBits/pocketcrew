# 部品: コピー用ボタン

## 何ができるか

テキストを1タップでクリップボードにコピーするボタン。1つの room に複数個置ける(例:
「本文をコピー」「タグをコピー」のように、元の1本のテキストを本文と末尾のタグ行に自動で
分けて、別々のボタンでコピーできるようにする)。コピーは素の文字列そのまま(改行そのまま)。
HTML化はしない。

## いつ使う

- room の中身が「1本のテキストを、貼り先(SNS・チャット・メモアプリなど)にコピペしたい」
  形のとき
- テキストの末尾に `#タグ1 #タグ2` のような行がついていて、本文とタグを別々にコピーしたい
  とき(本文だけ貼りたい・タグだけ貼りたい、が両方ある場面)
- ユーザーが「コピーしたい」「貼り付けたい」と言ったら、まず疑いなくこの部品

## 組み込み方

### api.py 側: 本文とタグを分ける

末尾から見て「空行」か「# で始まる行」が連続するかたまりをタグ部として切り出す純粋関数。
room の api.py にそのまま置ける(ファイルの読み書きが要る場合は `util.safe_path()` 経由で
読んだテキストをこの関数に渡す)。

```python
def split_trailing_tags(text):
    """テキストを (本文, タグ部) に分ける(純粋関数)。

    CRLF は LF に正規化する。末尾から見て「空行」か「# で始まる行」が連続する最大の
    かたまりをタグ部として切り出す(空行を挟んで複数行に分かれていてもまとめてタグ扱い)。
    タグ部の前後の空行は削るが、内部の改行・空行はそのまま残す。
    本文側は末尾の空行(空白だけの行を含む)を削るだけで、内部の改行・空行はそのまま残す。
    本文の途中に # で始まる行があっても(その後に普通の行が続く限り)本文の一部として扱う。
    タグ部が見つからなければ タグ部 は空文字列。

    >>> split_trailing_tags("本文だけ")
    ('本文だけ', '')
    >>> split_trailing_tags("本文\\n\\n#tag1 #tag2")
    ('本文', '#tag1 #tag2')
    >>> split_trailing_tags("見出し\\n#まだ本文\\n続き\\n\\n#tag1\\n#tag2")
    ('見出し\\n#まだ本文\\n続き', '#tag1\\n#tag2')
    >>> split_trailing_tags("\\n\\n")
    ('', '')
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    while lines and lines[-1].strip() == "":
        lines.pop()
    if not lines:
        return "", ""
    i = len(lines)
    while i > 0:
        s = lines[i - 1].strip()
        if s == "" or s.startswith("#"):
            i -= 1
        else:
            break
    body_lines, tag_lines = lines[:i], lines[i:]
    while tag_lines and tag_lines[0].strip() == "":
        tag_lines.pop(0)
    while tag_lines and tag_lines[-1].strip() == "":
        tag_lines.pop()
    while body_lines and body_lines[-1].strip() == "":
        body_lines.pop()
    return "\n".join(body_lines), "\n".join(tag_lines)
```

タグを分ける必要が無ければ、この関数は使わず元のテキストをそのまま1個のボタンでコピーすれば
よい(ボタンを1つだけ置く)。

### page.html 側: CSS

`_template` の配色変数(`--bg --fg --sub --dim --card --line --warn --acc`)と
`#mm-root` のスコープの書き方をそのまま使う。ボタンは最低 48px の高さにする(指で押しやすく
するため。`_template` 標準のボタンは 44px なので、コピー用ボタンはひとまわり大きくする)。

```css
#mm-root .btnrow{display:flex;gap:8px;margin:8px 0}
#mm-root button.copy{flex:1;background:var(--card);color:var(--fg);border:1px solid var(--line);
  border-radius:12px;padding:12px 10px;font-size:var(--fs-body);font-family:inherit;min-height:48px}
#mm-root button.copy:active{opacity:.7}
#mm-root button.copy:disabled{color:var(--sub);opacity:.5}
#mm-root .flash{font-size:var(--fs-sub);color:var(--sub);margin:4px 2px 10px;min-height:1.6em}
#mm-root .flash.ok{color:var(--acc)}
#mm-root .flash.bad{color:var(--warn)}
```

```html
<div class="btnrow">
  <button class="copy" id="mm-copy-body">本文をコピー</button>
  <button class="copy" id="mm-copy-tags">タグをコピー</button>
</div>
<div class="flash" id="mm-flash" aria-live="polite"></div>
```

### page.js 側: コピー本体

クリップボード API は http 配信(証明書なしのローカル環境など)や一部のブラウザで使えない
ことがあるので、隠し `<textarea>` + `execCommand('copy')` に落とすフォールバックを必ず持つ。
どちらの経路でも渡した素の文字列(改行そのまま)をそのままコピーする。

```js
function flash(el, ok, text) {
  el.textContent = text;
  el.className = 'flash ' + (ok ? 'ok' : 'bad');
  setTimeout(() => {
    if (el.textContent === text) { el.textContent = ''; el.className = 'flash'; }
  }, 2000);
}

function copyViaTextarea(text) {
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;top:0;left:-9999px;opacity:0;font-size:16px';
  document.body.appendChild(ta);
  ta.focus();
  ta.setSelectionRange(0, text.length);
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  document.body.removeChild(ta);
  return ok;
}

async function copyText(text, flashEl) {
  text = text || '';
  let ok = false;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
      ok = true;
    }
  } catch (e) {
    ok = false;
  }
  if (!ok) ok = copyViaTextarea(text);
  flash(flashEl, ok, ok ? 'コピーしました' : 'コピーできませんでした');
}

// 呼び出し側の配線の例
const flashEl = document.getElementById('mm-flash');
document.getElementById('mm-copy-body').addEventListener('click', () => copyText(bodyText, flashEl));
document.getElementById('mm-copy-tags').addEventListener('click', () => copyText(tagsText, flashEl));
```

### サブ変体: 書式つき(HTML)でコピー

貼り先が Markdown をそのまま文字として貼ってしまうエディタ(見出し・太字・箇条書きを保った
まま貼りたい場面)では、クリップボードに `text/html` も一緒に載せる。SNS のキャプションの
ような「素のテキストで十分」な場面では使わない(上のプレーン版で足りる)。

```js
async function copyHtml(html, plain, flashEl) {
  try {
    if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
      await navigator.clipboard.write([new ClipboardItem({
        'text/html': new Blob([html], { type: 'text/html' }),
        'text/plain': new Blob([plain], { type: 'text/plain' }),
      })]);
      flash(flashEl, true, 'コピーしました(書式つき)');
      return;
    }
  } catch (e) {
    // ClipboardItem が無い/拒否された環境は下の execCommand に落とす
  }
  flash(flashEl, copyViaSelection(html), 'コピーしました(選択経由)');
}

// 保険: 画面外の contenteditable に HTML を入れて選択 → execCommand('copy')。
// この経路でも書式つき(text/html)で載る。
function copyViaSelection(html) {
  const stage = document.getElementById('mm-stage'); // 画面には出さない contenteditable
  stage.innerHTML = html;
  const range = document.createRange();
  range.selectNodeContents(stage);
  const sel = window.getSelection();
  sel.removeAllRanges();
  sel.addRange(range);
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  sel.removeAllRanges();
  stage.innerHTML = '';
  return ok;
}
```

`#mm-stage` は画面外に置く隠し要素(`position:fixed;left:-9999px;...` かつ
`contenteditable="true"`)を `page.html` に1つ足す。

## 確認のしかた

390px 幅の画面で:

- ボタンが横に並んで見切れず、指の腹で押せる大きさ(48px 以上)になっているか
- ボタンを押すと「コピーしました」がボタンの下(または近く)に一瞬出て、約2秒で消えるか
- コピーしたものを実際にメモアプリなどに貼って、改行がそのまま残っているか(本文とタグを
  分けている場合は、それぞれ正しく分かれているか)
- (書式つき版を使う場合)貼り先で見出し・太字・箇条書きが保たれているか

## つまずき

- **http 配信だとコピーできない**: `navigator.clipboard` はセキュアコンテキスト(https、また
  は localhost)でしか使えない。`execCommand` フォールバックを必ず用意する(このページの
  コード例はすでに両方持っている)
- **「コピーしました」が消えない/次のタップで残る**: `flash()` は「自分が出したテキストの
  ままなら消す」判定にしてあるので、連打しても文字化けしない。自作するときも同じガードを
  入れる
- **タグの分割がずれる**: `split_trailing_tags` は「末尾から見た連続する空行/#行」しか見て
  いない。本文の途中に `#` 始まりの行があっても、そのあとに普通の行が続けば本文側に残る
  (これは仕様どおり)
- **書式つきコピーが効かない環境がある**: `ClipboardItem` 非対応のブラウザでは自動的に
  `execCommand` 経由に落ちる。落ちても書式は保たれるが、環境によっては失敗することがあるので
  プレーン版のボタンも残しておくと安全
