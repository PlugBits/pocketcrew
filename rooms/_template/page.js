// メモ室のページ用スクリプト。
// room id は自分自身の <script src> から読み取る(フォルダをコピーしただけで動くように、
// ここでは room 名をハードコードしない。page.html の <script src> だけは書き換えが要る)。
(() => {
  const ROOM = (() => {
    try {
      const src = document.currentScript.src;                 // 例: https://.../reading.js
      const m = src.match(/\/([^/?]+?)(?:\/page)?\.js(?:\?|$)/);
      if (m) return m[1];
    } catch (e) { /* 取れなければ URL から推測する */ }
    return location.pathname.replace(/^\//, '') || 'memo';
  })();
  const API = `/api/${ROOM}`;

  const listEl = document.getElementById('mm-list');
  const inputEl = document.getElementById('mm-input');
  const addBtn = document.getElementById('mm-add');
  const errEl = document.getElementById('mm-err');

  function esc(s) { return String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c])); }

  async function load() {
    try {
      const r = await fetch(API, { cache: 'no-store' });        // GET /api/<room>
      const j = await r.json();
      const items = j.items || [];
      listEl.innerHTML = items.length
        ? items.map(t => `<div class="item">${esc(t)}</div>`).join('')
        : '<div class="none">まだ何もありません</div>';
    } catch (e) {
      listEl.innerHTML = '<div class="none">読み込めませんでした</div>';
    }
  }

  async function add() {
    const text = inputEl.value.trim();
    if (!text) return;
    addBtn.disabled = true;
    errEl.style.display = 'none';
    try {
      const r = await fetch(API + '/add', {                     // POST /api/<room>/add
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      const j = await r.json();
      if (!j.ok) throw new Error(j.error || '失敗しました');
      inputEl.value = '';
      await load();
    } catch (e) {
      errEl.textContent = '追加できませんでした: ' + e.message;
      errEl.style.display = 'block';
    } finally {
      addBtn.disabled = false;
    }
  }

  addBtn.addEventListener('click', add);
  inputEl.addEventListener('keydown', e => { if (e.key === 'Enter') add(); });
  load();
})();
