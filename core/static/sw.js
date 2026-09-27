// ポケクル service worker: シェルのキャッシュ(stale-while-revalidate)とプッシュ通知
const VERSION = '__VERSION__';
const CACHE = 'shell-' + VERSION;
const clog = (o) => fetch('/api/clientlog', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ src: 'sw', ver: VERSION, ...o }) }).catch(() => {});
// 配列は /sw.js 配信時にサーバー側で埋める(core固定 + rooms.shell_paths() の重複なし合併)。プレースホルダの前後に他の文字は置かないこと(置換は文字列一致)
const SHELL = __SHELL__;
// 同じく配信時に埋める(core固定 + rooms.dynamic_paths())。「毎回サーバー側で描画する動的ページ
// (個人データを含みうる)」の一覧。プレースホルダの扱いは SHELL と同じ
const DYNAMIC = __DYNAMIC__;

self.addEventListener('install', e => {
  // 新しい SW を即座に待機列から有効化する(2回開かないと更新が反映されない問題を避ける)。
  // ページ側の SKIP_WAITING メッセージは互換のため残す(no-op フォールバック)。
  // install ハンドラの先頭で同期的に呼ぶ(非同期処理の後だと反映が遅れる/されない環境があるため)
  self.skipWaiting();
  e.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // どれか1つが失敗しても install 自体は成功させる
    await Promise.all(SHELL.map(u => cache.add(u).catch(() => {})));
  })());
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k.startsWith('shell-') && k !== CACHE).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

// ページからの「更新を適用して」の合図でだけ即時に有効化する(勝手な skipWaiting はしない)
self.addEventListener('message', e => {
  if (e.data && e.data.type === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith('/api/')) return;      // API はネットワークのみ(キャッシュしない)
  if (!SHELL.includes(url.pathname)) return;         // シェル以外もネットワークのみ

  // HTML は常に最新を優先(更新が2回開かないと届かない問題を避ける)。取れなければキャッシュ。
  // DYNAMIC に載っているパス(毎回サーバー側で描画する動的ページ。個人データを含みうる)は
  // '/'・'/plan' と同じ扱いにする(キャッシュを先に出すと古い個人データが一瞬見える事故になる)。
  if (DYNAMIC.includes(url.pathname)) {
    e.respondWith((async () => {
      const cache = await caches.open(CACHE);
      try {
        const ctrl = new AbortController(); const tm = setTimeout(() => ctrl.abort(), 1500);
        const res = await fetch(req, { signal: ctrl.signal }); clearTimeout(tm);
        if (res && res.ok) cache.put(req, res.clone());
        return res;
      } catch (_) {
        const cached = await cache.match(req);
        return cached || new Response('offline', { status: 503 });
      }
    })());
    return;
  }
  const update = (async () => {
    try {
      const cache = await caches.open(CACHE);
      const res = await fetch(req);
      if (res && res.ok) cache.put(req, res.clone());
      return res;
    } catch (_) { return null; }
  })();
  e.waitUntil(update.catch(() => {}));
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const cached = await cache.match(req);
    if (cached) return cached;                       // 即返す。裏で update が取り直す
    const fresh = await update;
    return fresh || new Response('offline', { status: 503 });
  })());
});

self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { title: 'ポケクル', body: e.data && e.data.text() }; }
  e.waitUntil(Promise.all([
    clog({ ev: 'push', title: d.title, url: d.url, tag: d.tag }),
    self.registration.showNotification(d.title || 'ポケクル', {
      body: d.body || '', tag: d.tag || undefined, data: { url: d.url || '/' }, renotify: !!d.tag,
    }),
  ]));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  const m = url.match(/#t=([^&]+)/); const win = m ? decodeURIComponent(m[1]) : '';
  // 開く処理を最優先。ログは待たずに投げるだけ
  const logP = clog({ ev: 'click', url, win });
  e.waitUntil((async () => {
    let list = [];
    try { list = await self.clients.matchAll({ type: 'window', includeUncontrolled: true }); } catch (_) {}
    clog({ ev: 'clients', n: list.length });
    await logP;
    const c = list.find(x => 'focus' in x) || list[0];
    if (c) {
      try { if (win) c.postMessage({ type: 'open', window: win }); } catch (_) {}
      try { await c.focus(); } catch (err) { clog({ ev: 'focus-error', err: String(err) }); }
      clog({ ev: 'posted', win });
      return;
    }
    try { await self.clients.openWindow(url); clog({ ev: 'openWindow', url }); }
    catch (err) { clog({ ev: 'openWindow-error', err: String(err) }); }
  })());
});
