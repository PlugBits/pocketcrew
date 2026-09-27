// vault 閲覧(読み取り専用)。ホーム画面(index.html)に room.json の "home" キーで差し込まれる
// (core/rooms.py の docstring参照)。core の主スクリプトは IIFE で閉じているので、ここは完全に
// 自己完結(自分の DOM・変数はすべて自分で持つ)。core とやり取りするのは window.TP だけ:
//   TP.menuActions.vault = ...   ⋯メニューの「📁 vault」から呼ばれる
//   TP.linkifiers.push(...)      チャット本文の ~/vault/... を linkify する
//   TP.openBlob(url,title)       vault ビューア内の画像タップ→#blobview オーバーレイ
(() => {
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// ================= #files オーバーレイの DOM(自分で作る) =================
document.body.insertAdjacentHTML('beforeend',
  '<div id="files" class="tp-overlay"><div class="top"><button id="fback">←</button>' +
  '<span class="path" id="fpath">vault</span><button id="fraw" class="dim" style="display:none">raw</button>' +
  '<button id="fclose">閉じる</button></div><div class="list" id="flist"></div></div>');
const filesEl = document.getElementById('files'), flist = document.getElementById('flist'),
      fpath = document.getElementById('fpath'), fraw = document.getElementById('fraw');
let fcur = '', fmode = 'dir', fdoc = null, rawMode = false;

function fmtTime(ts) { const d = new Date(ts * 1000); return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`; }
function fmtSize(n) { return n < 1024 ? n + 'B' : n < 1048576 ? (n / 1024).toFixed(1) + 'K' : (n / 1048576).toFixed(1) + 'M'; }
function vaultHref(path) { const rel = path.replace(/^~\/vault\//, ''); return (rel.endsWith('/') ? '#d=' : '#f=') + encodeURIComponent(rel.replace(/\/$/, '')); }
const VAULT_PATH_RE = /(^|[\s(「])(~\/vault\/(?:[^\s<>"'()（）」]+?\.(?:md|json|csv|txt|png|jpe?g|webp)|[^\s<>"'()（）」]+\/))/g;

async function openDir(rel) {
  const j = await (await fetch('/api/vault/ls?p=' + encodeURIComponent(rel), { cache: 'no-store' })).json();
  if (!j.ok) { alert(j.error); return; }
  fcur = rel; fmode = 'dir'; fraw.style.display = 'none'; fpath.textContent = 'vault/' + rel; filesEl.classList.add('on');
  flist.innerHTML = j.dirs.map(d => `<div class="fi" data-d="${esc(d)}"><span>📁</span><span class="n">${esc(d)}</span></div>`).join('') +
    j.files.map(f => `<div class="fi" data-f="${esc(f.name)}"><span>${f.image ? '🖼️' : '📄'}</span><span class="n">${esc(f.name)}</span><span class="m">${fmtTime(f.mtime)} · ${fmtSize(f.size)}</span></div>`).join('') || '<div class="none" style="padding:20px;color:var(--dim)">(空)</div>';
  flist.scrollTop = 0;
}
// 画像(2026-09-21): api_file() は TEXT_EXT しか返さないので、画像は /api/img から <img> で開く。
// img で出しておけば、ピンチの拡大も長押しの保存も iOS Safari の標準の動きに任せられる。
const IMG_EXT = /\.(png|jpe?g|webp|gif)$/i;
function openImage(rel) {
  fdoc = null; fmode = 'file'; fpath.textContent = 'vault/' + rel; fraw.style.display = 'none';
  filesEl.classList.add('on');
  flist.innerHTML = `<div class="imgwrap"><img class="vimg" src="/api/img?p=${encodeURIComponent(rel)}" alt="${esc(rel.split('/').pop())}"></div>` +
    `<p class="imgnote">ピンチで拡大、長押しで保存できます</p>`;
  flist.scrollTop = 0;
  const im = flist.querySelector('img');
  im.addEventListener('error', () => { flist.innerHTML = '<div class="none" style="padding:20px;color:var(--dim)">画像を開けませんでした</div>'; });
}
async function openFile(rel) {
  if (IMG_EXT.test(rel)) { openImage(rel); return; }
  const j = await (await fetch('/api/file?p=' + encodeURIComponent(rel), { cache: 'no-store' })).json();
  if (!j.ok) { alert(j.error); return; }
  fdoc = j; fmode = 'file'; fpath.textContent = 'vault/' + j.path; fraw.style.display = ''; filesEl.classList.add('on'); renderFile(); flist.scrollTop = 0;
}
function renderFile() {
  if (!fdoc) return; fraw.textContent = rawMode ? 'md' : 'raw';
  const baseDir = fdoc.path.split('/').slice(0, -1).join('/');
  flist.innerHTML = rawMode || !/\.md$/i.test(fdoc.path) ? `<pre class="md" style="white-space:pre-wrap;font-family:var(--font-mono);font-size:var(--fs-sub);line-height:var(--lh)">${esc(fdoc.text)}</pre>` : `<div class="md">${md(fdoc.text, baseDir)}</div>`;
}
flist.addEventListener('click', e => {
  const el = e.target.closest('.fi'); if (!el) return;
  if (el.dataset.d !== undefined) openDir((fcur ? fcur + '/' : '') + el.dataset.d);
  else if (el.dataset.f !== undefined) openFile((fcur ? fcur + '/' : '') + el.dataset.f);
});
document.getElementById('fback').addEventListener('click', () => { if (fmode === 'file') { openDir(fcur); } else if (fcur) { openDir(fcur.split('/').slice(0, -1).join('/')); } else closeFiles(); });
// 閉じたら #f=/#d= を消す(2026-09-24)。残すと同じファイルのリンクを再タップしても hashchange が起きず開かない
function closeFiles() { filesEl.classList.remove('on'); if (/^#[fd]=/.test(location.hash)) history.replaceState(null, '', location.pathname + location.search); }
document.getElementById('fclose').addEventListener('click', closeFiles);
fraw.addEventListener('click', () => { rawMode = !rawMode; renderFile(); });

// #f=path.md / #d=dir で直接開ける(ホーム画面追加やリンク用)。チャット本文の ~/vault/... リンクも
// このハッシュを使うので、タップすればページ内のこのビューアで開く(別ナビゲーションはしない)。
function handleHash() {
  if (location.hash.startsWith('#f=')) openFile(decodeURIComponent(location.hash.slice(3)));
  else if (location.hash.startsWith('#d=')) openDir(decodeURIComponent(location.hash.slice(3)));
}
handleHash();
window.addEventListener('hashchange', handleHash);

// 簡易 Markdown(見出し・箇条書き・番号・引用・コード・強調・リンク・チェックボックス・表・frontmatter)
// これは vault ビューア専用の描画(チャットの吹き出しでは使わない)
function inline(s) {
  s = esc(s);
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>').replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>')
    .replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (m, a, b) => `<a href="#" data-wl="${a}">${b || a}</a>`)
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|\s)(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>')
    .replace(VAULT_PATH_RE, (m, a, pth) => `${a}<a href="${vaultHref(pth)}">${pth}</a>`);
  return s;
}
function imgSrc(rel, baseDir) { if (/^https?:\/\//i.test(rel)) return rel; const p = (baseDir ? baseDir + '/' : '') + rel; return '/api/img?p=' + encodeURIComponent(p); }   // 2026-09-24: blob は docs-inquiry 限定で、他の md の画像が壊れていた
function md(src, baseDir) {
  baseDir = baseDir || '';
  // <details>...</details>(元の記録)は独立して取り出し、末尾に付け直す。中身はエスケープして段落に
  let detailsHtml = '';
  const dm = src.match(/<details>([\s\S]*?)<\/details>/);
  if (dm) {
    src = src.slice(0, dm.index) + src.slice(dm.index + dm[0].length);
    const sm = dm[1].match(/^\s*<summary>([\s\S]*?)<\/summary>/);
    const body = sm ? dm[1].slice(sm.index + sm[0].length) : dm[1];
    const paras = body.split(/\n\s*\n/).map(s => s.trim()).filter(Boolean).map(p => `<p>${inline(p.replace(/\n/g, ' '))}</p>`).join('');
    detailsHtml = `<details>${sm ? `<summary>${inline(sm[1])}</summary>` : ''}${paras}</details>`;
  }
  const out = []; let lines = src.replace(/\r/g, '').split('\n'); let i = 0;
  if (lines[0] === '---') { const j = lines.indexOf('---', 1); if (j > 0) { out.push(`<div class="fm">${esc(lines.slice(1, j).join('\n'))}</div>`); lines = lines.slice(j + 1); } }
  let list = null, para = [];
  const flushP = () => { if (para.length) { out.push(`<p>${inline(para.join(' '))}</p>`); para = []; } };
  const flushL = () => { if (list) { out.push(`</${list}>`); list = null; } };
  const appendToLastLi = (html) => { for (let k = out.length - 1; k >= 0; k--) { if (out[k].startsWith('<li>')) { out[k] = out[k].replace(/<\/li>$/, html + '</li>'); return true; } } return false; };
  while (i < lines.length) {
    const l = lines[i];
    if (/^```/.test(l)) { flushP(); flushL(); const buf = []; i++; while (i < lines.length && !/^```/.test(lines[i])) buf.push(lines[i++]); out.push(`<div class="cb"><button type="button" class="cbcopy">コピー</button><pre><code>${esc(buf.join('\n'))}</code></pre></div>`); i++; continue; }
    let m;
    if ((m = l.match(/^\s*!\[([^\]]*)\]\(([^)]+)\)\s*$/))) { const imgHtml = `<img src="${imgSrc(m[2], baseDir)}" alt="${esc(m[1])}">`; if (list && appendToLastLi(imgHtml)) { } else { flushP(); flushL(); out.push(imgHtml); } }
    else if ((m = l.match(/^(#{1,6})\s+(.*)/))) { flushP(); flushL(); out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`); }
    else if (/^\s*(-{3,}|\*{3,})\s*$/.test(l)) { flushP(); flushL(); out.push('<hr>'); }
    else if ((m = l.match(/^\s*[-*+]\s+\[( |x|X)\]\s+(.*)/))) { flushP(); if (list !== 'ul') { flushL(); out.push('<ul>'); list = 'ul'; } out.push(`<li><input type="checkbox" disabled ${m[1] !== ' ' ? 'checked' : ''}>${inline(m[2])}</li>`); }
    else if ((m = l.match(/^\s*[-*+]\s+(.*)/))) { flushP(); if (list !== 'ul') { flushL(); out.push('<ul>'); list = 'ul'; } out.push(`<li>${inline(m[1])}</li>`); }
    else if ((m = l.match(/^\s*\d+[.)]\s+(.*)/))) { flushP(); if (list !== 'ol') { flushL(); out.push('<ol>'); list = 'ol'; } out.push(`<li>${inline(m[1])}</li>`); }
    else if ((m = l.match(/^>\s?(.*)/))) { flushP(); flushL(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); }
    else if (/^\|.*\|\s*$/.test(l)) {
      flushP(); flushL(); const rows = []; while (i < lines.length && /^\|.*\|\s*$/.test(lines[i])) { rows.push(lines[i]); i++; }
      const cells = r => r.trim().slice(1, -1).split('|').map(c => inline(c.trim())); const body = rows.filter(r => !/^\|\s*:?-+/.test(r));
      out.push('<div style="overflow:auto"><table style="border-collapse:collapse;font-size:14px;width:100%">' + body.map((r, k) => `<tr>${cells(r).map(c => `<${k ? 'td' : 'th'} style="border:1px solid var(--line);padding:6px 8px;text-align:left;line-height:1.6">${c}</${k ? 'td' : 'th'}>`).join('')}</tr>`).join('') + '</table></div>'); continue;
    }
    else if (!l.trim()) { flushP(); flushL(); }
    else para.push(l);
    i++;
  }
  flushP(); flushL(); return out.join('\n') + detailsHtml;
}
flist.addEventListener('click', e => { const a = e.target.closest('a[data-wl]'); if (a) { e.preventDefault(); const name = a.dataset.wl; const dir = fdoc ? fdoc.path.split('/').slice(0, -1).join('/') : ''; openFile((dir ? dir + '/' : '') + name.replace(/\.md$/, '') + '.md'); } });
// vault ビューア内の画像タップ: 別ナビゲーションではなく #blobview オーバーレイで開く(PWAスタンドアロンに戻る手段が無いため)
flist.addEventListener('click', e => { const img = e.target.closest('img'); if (img && window.TP && TP.openBlob) { e.preventDefault(); TP.openBlob(img.getAttribute('src'), img.getAttribute('alt') || img.getAttribute('src').split('/').pop()); } });

// コードブロックのコピー(2026-09-25)。md の枠の中身を携帯から別アプリ(Gemini の Gem の指示欄など)
// へ貼るため。``` と言語名は含めず中身だけ。iOS で navigator.clipboard が使えない/拒まれたときは、
// 画面外の textarea を選択して execCommand('copy') に落とす(タップの処理の中で呼ぶので iOS でも通る)。
function copyText(text) {
  const legacy = () => {
    const ta = document.createElement('textarea');
    ta.value = text; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;font-size:16px';
    document.body.appendChild(ta); ta.focus(); ta.setSelectionRange(0, text.length);
    let ok = false; try { ok = document.execCommand('copy'); } catch (e) { }
    document.body.removeChild(ta); return ok;
  };
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text).then(() => true, legacy);
  return Promise.resolve(legacy());
}
flist.addEventListener('click', e => {
  const b = e.target.closest('.cbcopy'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const code = b.parentElement.querySelector('pre code'); if (!code) return;
  copyText(code.textContent).then(ok => {
    b.textContent = ok ? 'コピーしました' : 'コピーできませんでした'; b.classList.toggle('done', ok);
    clearTimeout(b._t); b._t = setTimeout(() => { b.textContent = 'コピー'; b.classList.remove('done'); }, 1600);
  });
});

// ================= core との結びつけ =================
window.TP = window.TP || { linkifiers: [], menuActions: {} };
TP.menuActions.vault = () => openDir('');
TP.linkifiers.push(h => h.replace(VAULT_PATH_RE, (m, a, pth) => `${a}<a href="${vaultHref(pth)}">${pth}</a>`));
})();
