"""room(機能のフォルダ1つ)の読み込みと、core への登録。

rooms/ と rooms-private/ の直下のフォルダを1つずつ room として読む(名前が "_" で始まるものは見本なので読まない)。

room のファイル(room.json 以外はどれも任意):
  room.json   {"name": "ワークアウト", "icon": "🏋️", "order": 40,
               "menu": true | [{"label": "...", "href": "/x", "order": 10}, ...],   ⋯メニューに出す
                      href の代わりに "act": "vault" を書くと、押したときに location.href ではなく
                      ホーム画面の TP.menuActions["vault"]() を呼ぶ(home.js が登録する。用途は下記 "home" 参照)。
               "tab_in": "plan",          plan ページにタブとして差し込む(tab.js を読む)
               "home": ["home.css", "home.js"],  ホーム画面(index.html)に差し込む(下記参照)
               "cache": ["/x", ...]}      sw.js のキャッシュ対象に足すパス(page/page.js/home.css/home.js は自動)
  page.html   /<room> で配信(<script src="/<room>.js"> に ?v= が付く)
  page.js     /<room>.js と /<room>/page.js で配信
  tab.js      /<room>/tab.js で配信(tab_in のページが読み込む)
  home.css    /<room>/home.css で配信。room.json の "home" にあれば、ホーム画面の <head> 直後に
  home.js     /<room>/home.js で配信。          <link rel=stylesheet ?v=> として core が差し込む。
                      home.js は <script> として、ホーム画面の本体スクリプト(core の主 IIFE)の
                      閉じタグ直後に差し込まれる(?v= 付き)。ホーム画面はスタンドアロン PWA で
                      「戻る」が無いページ遷移をしないタブ1枚なので、room がホームに機能を足す
                      唯一の経路はこれ(別ページに飛ばすと PWA では行き止まりになる)。
                      core の主スクリプトは IIFE で閉じているので、home.js は自分の変数・DOM
                      (オーバーレイなど)を自分で作る自己完結のスクリプトにする。core とやり取り
                      するのは window.TP だけ(TP.linkifiers・TP.menuActions・TP.openBlob。
                      index.html 冒頭のコメント参照)。全画面オーバーレイを作るときは class="tp-overlay"
                      を付ける(スレ→ホームのスワイプ判定 swipeOverlayOpen() が汎用的に見ている)。
  static/     /<room>/static/<file> で配信
  api.py      ROUTES = {"GET /": fn, "POST /toggle": fn}  → /api/<room>, /api/<room>/toggle
              LEGACY = {"GET /api/plan": "GET /", "GET /scene/*": "GET /scene"}  旧パスの別名(末尾 * は前方一致)
              fn(req) は dict/list(→JSON)か Resp を返す。None は 404。
  jobs.py     JOBS  = [{"name": "brief", "at": "07:30", "fn": fn}, {"name": "x", "every": "minute", "fn": fn}]
                      "at" は時刻を過ぎたら毎分呼ぶ(追いつき方式)。二重実行は fn 側で done() / mark_done() を使って防ぐ。
                      "weekday": 6 で曜日を限定(月=0)。
              START = [fn]            起動時に別スレッドで1回呼ぶ(常駐ワーカー用)
              BRIEF = fn(day) -> [{"order": 10, "lines": [...], "push": "...", "join": False}]
                      朝の便りの段。order 順に並べ、段の間は空行(join=True なら前の段に続ける)。push は通知本文の断片。

決まり:
  - room 同士は import しない。共有するのは vault のファイルと core だけ(from core import config, collect, util)。
  - room のフォルダは sys.path に足すので、room 内の補助モジュールは room 名を頭に付けるなど、他と被らない名前にする。
  - 読み込みに失敗した room は無効にして warnings() に1行残す。core は落とさない。
  - config.toml の [rooms.<room>] enabled = false で無効にできる。room 固有の設定もここに書く(room_config())。
"""
import importlib.util
import json
import os
import re
import sys
import threading
import time
import traceback

from core import config as C
from core import util

ROOM_DIRS = [os.path.join(C.APP_DIR, "rooms"), os.path.join(C.APP_DIR, "rooms-private")]


class Resp:
    """JSON 以外を返すとき用(HTML・画像・リダイレクトなど)"""
    def __init__(self, code=200, ctype="text/plain; charset=utf-8", body=b"", headers=None):
        self.code, self.ctype, self.headers = code, ctype, headers or {}
        self.body = body.encode("utf-8") if isinstance(body, str) else body


class Req:
    """ハンドラに渡す要求。handler は BaseHTTPRequestHandler(SSE など特殊な応答で直接書くとき用)"""
    def __init__(self, handler, method, path, query, read_body):
        self.handler, self.method, self.path = handler, method, path
        self.query = query                     # parse_qs の結果(値はリスト)
        self._read_body = read_body
        self._body = None
        self.sub = ""                          # 前方一致(*)で当たったときの残りのパス

    def q(self, name, default=""):
        return self.query.get(name, [default])[0]

    def body(self, limit=20_000_000):
        if self._body is None:
            self._body = self._read_body(limit) or b""
        return self._body

    def json(self):
        try:
            return json.loads(self.body(2_000_000) or b"{}")
        except Exception:
            return {}


class Room:
    def __init__(self, rid, path, private):
        self.id, self.dir, self.private = rid, path, private
        self.meta, self.api, self.jobs, self.error = {}, None, None, None

    def file(self, name):
        p = os.path.join(self.dir, name)
        return p if os.path.isfile(p) else None

    def info(self):
        m = self.meta
        return {"id": self.id, "name": m.get("name", self.id), "icon": m.get("icon", ""),
                "order": m.get("order", 100), "private": self.private, "error": self.error,
                "menu": menu_items(self), "tab_in": m.get("tab_in"),
                "tab": f"/{self.id}/tab.js" if self.file("tab.js") else None}


ROOMS = {}          # id -> Room(読み込めたものも失敗したものも)
_ROUTES = {}        # (method, path) -> (room, fn)
_PREFIX = []        # [(method, prefix, room, fn)] 長い順
_WARN = []


def room_config(rid):
    return C.RAW.get("rooms", {}).get(rid, {})


def _import(room, name):
    p = room.file(name)
    if not p:
        return None
    mod_name = f"room_{room.id.replace('-', '_')}_{name[:-3]}"
    spec = importlib.util.spec_from_file_location(mod_name, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _mount(room):
    api = room.api
    if not api:
        return
    for key, fn in getattr(api, "ROUTES", {}).items():
        method, sub = key.split(" ", 1)
        path = f"/api/{room.id}" + ("" if sub == "/" else sub)
        _ROUTES[(method, path)] = (room, fn)
    for old, key in getattr(api, "LEGACY", {}).items():
        method, oldpath = old.split(" ", 1)
        _, sub = key.split(" ", 1)
        fn = dict((k.split(" ", 1)[1], v) for k, v in getattr(api, "ROUTES", {}).items() if k.startswith(method + " ")).get(sub)
        if fn is None:
            raise ValueError(f"LEGACY {old} → {key} の先が ROUTES にありません")
        if oldpath.endswith("*"):
            _PREFIX.append((method, oldpath[:-1], room, fn))
        else:
            _ROUTES[(method, oldpath)] = (room, fn)


def load_all():
    ROOMS.clear(); _ROUTES.clear(); _PREFIX.clear(); _WARN.clear()
    for base in ROOM_DIRS:
        if not os.path.isdir(base):
            continue
        private = base.endswith("rooms-private")
        for rid in sorted(os.listdir(base)):
            path = os.path.join(base, rid)
            if rid.startswith(("_", ".")) or not os.path.isdir(path) or not os.path.isfile(os.path.join(path, "room.json")):
                continue
            if rid in ROOMS:
                _WARN.append(f"room {rid}: 同じ名前が2つあります({path} は読みません)")
                continue
            room = Room(rid, path, private)
            ROOMS[rid] = room
            if room_config(rid).get("enabled", True) is False:
                room.error = "disabled"
                continue
            try:
                with open(os.path.join(path, "room.json"), encoding="utf-8") as f:
                    room.meta = json.load(f)
                if path not in sys.path:
                    sys.path.insert(0, path)
                room.api = _import(room, "api.py")
                room.jobs = _import(room, "jobs.py")
                _mount(room)
            except Exception as e:
                room.error = f"{type(e).__name__}: {e}"
                room.api = room.jobs = None
                _WARN.append(f"room {rid} を読み込めませんでした: {room.error}")
                traceback.print_exc()
    _PREFIX.sort(key=lambda x: -len(x[1]))
    # 失敗した room のルートが半端に残らないように、成功した room だけで張り直す
    for k in [k for k, (r, _) in _ROUTES.items() if r.error]:
        del _ROUTES[k]
    _PREFIX[:] = [x for x in _PREFIX if not x[2].error]
    return ROOMS


def active():
    return sorted((r for r in ROOMS.values() if not r.error), key=lambda r: (r.meta.get("order", 100), r.id))


def warnings():
    return list(_WARN)


def menu_items(room):
    m = room.meta.get("menu")
    if not m:
        return []
    if m is True:
        label = (room.meta.get("icon", "") + " " + room.meta.get("name", room.id)).strip()
        return [{"label": label, "href": f"/{room.id}", "order": room.meta.get("order", 100)}]
    return [{"order": room.meta.get("order", 100), **x} for x in m]


def menu():
    """⋯メニューに出す項目(order 順)。core の項目(vault・新しいスレ)は index.html 側で order を持って混ぜる"""
    items = [x for r in active() for x in menu_items(r)]
    return sorted(items, key=lambda x: x["order"])


def shell_paths():
    """sw.js のキャッシュ対象に足すパス"""
    out = []
    for r in active():
        if r.file("page.html"):
            out.append(f"/{r.id}")
        if r.file("page.js"):
            out.append(f"/{r.id}.js")
        if r.file("tab.js"):
            out.append(f"/{r.id}/tab.js")
        if r.file("home.css"):
            out.append(f"/{r.id}/home.css")
        if r.file("home.js"):
            out.append(f"/{r.id}/home.js")
        out += r.meta.get("cache", [])
    return out


def dynamic_paths():
    """sw.js が「常にネットワーク優先(古いキャッシュを一瞬でも出さない)」で扱うページパス。
    room.json の "cache" のうち拡張子を持たないもの(= サーバーが毎回描画する動的ページ。
    個人データを含みうる)だけを拾う。拡張子付き(.css/.js 等の静的アセット)は shell_paths() 側の
    通常キャッシュに任せて、ここには含めない。"""
    out = []
    for r in active():
        for p in r.meta.get("cache", []):
            last = p.rsplit("/", 1)[-1]
            if "." not in last:
                out.append(p)
    return out


def home_assets():
    """ホーム画面(index.html)に差し込む room.json の "home" キー。存在する room だけ、
    room 順(order, id)で (room, filename) のペアを css/js に分けて返す。
    core/server.py がこれを使って <link>/<script> タグを組み立てる(?v= はそちらで付ける)。"""
    css, js = [], []
    for r in active():
        for name in r.meta.get("home", []):
            if not r.file(name):
                continue
            if name.endswith(".css"):
                css.append((r.id, name))
            elif name.endswith(".js"):
                js.append((r.id, name))
    return css, js


def asset_files():
    """シェル版(SHELL_VERSION)の計算に含めるファイル"""
    out = []
    for r in active():
        for name in ("room.json", "page.html", "page.js", "tab.js", "home.css", "home.js"):
            if r.file(name):
                out.append(r.file(name))
        sd = os.path.join(r.dir, "static")
        if os.path.isdir(sd):
            for root, _, files in os.walk(sd):
                out += [os.path.join(root, f) for f in sorted(files)]
        # room.json の "assets"(相対パス。例: ある room が web/app.css 等を宣言する)もハッシュに含める
        for rel in r.meta.get("assets", []):
            p = r.file(rel)
            if p:
                out.append(p)
    return out


# ---------- HTTP ----------
_TYPES = {".js": "application/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
          ".html": "text/html; charset=utf-8", ".json": "application/json; charset=utf-8",
          ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp",
          ".woff2": "font/woff2"}


def _static(room, rel):
    base = os.path.realpath(room.dir)
    p = os.path.realpath(os.path.join(base, rel))
    if not p.startswith(base + os.sep) or not os.path.isfile(p):
        return None
    with open(p, "rb") as f:
        return Resp(200, _TYPES.get(os.path.splitext(p)[1], "application/octet-stream"), f.read())


def _inject_tabs(rid, text):
    """rid のページに、tab_in==rid な room の tab.js を1つずつ、rid 自身の <script> タグの
    直後へ差し込む(段階3e: /api/rooms を待たずに最初の描画でタブバーが揃うように)。
    {{ROOM}} 置換の後・versioned_html() の前に呼ぶ(差し込んだ <script> にも ?v= が付くように)。"""
    tabs = [r for r in active() if r.meta.get("tab_in") == rid and r.file("tab.js")]
    if not tabs:
        return text
    injected = "".join(f'<script src="/{r.id}/tab.js"></script>' for r in tabs)
    own = re.compile(r'(<script src="/' + re.escape(rid) + r'(?:\.js|/page\.js)"[^>]*></script>)')
    new_text, n = own.subn(lambda m: m.group(1) + injected, text, count=1)
    if n == 1:
        return new_text
    return text + injected   # 自分の <script> が見当たらない(見本の書き方違反)ときは末尾に足す保険


def route(handler, method, path, query, read_body, versioned_html):
    """room に当たれば Resp を返す。当たらなければ None(core の既存ルートへ)。
    versioned_html(bytes) -> bytes は core が渡す(script の ?v= 付け)"""
    hit = _ROUTES.get((method, path))
    sub = ""
    if not hit:
        for m, prefix, room, fn in _PREFIX:
            if m == method and path.startswith(prefix):
                hit, sub = (room, fn), path[len(prefix):]
                break
    if hit:
        room, fn = hit
        req = Req(handler, method, path, query, read_body)
        req.sub = sub
        try:
            res = fn(req)
        except Exception as e:
            traceback.print_exc()
            return Resp(500, "application/json; charset=utf-8",
                        json.dumps({"ok": False, "error": f"{room.id}: {type(e).__name__}: {e}"}, ensure_ascii=False))
        if res is None:
            return Resp(404, "text/plain", b"not found")
        if isinstance(res, Resp):
            return res
        return Resp(200, "application/json; charset=utf-8", json.dumps(res, ensure_ascii=False))
    if method != "GET":
        return None
    parts = path.strip("/").split("/", 1)
    rid = parts[0][:-3] if (len(parts) == 1 and parts[0].endswith(".js")) else parts[0]
    room = ROOMS.get(rid)
    if not room or room.error:
        return None
    rest = parts[1] if len(parts) > 1 else ""
    if path == f"/{rid}" and room.file("page.html"):
        with open(room.file("page.html"), encoding="utf-8") as f:
            text = f.read().replace("{{ROOM}}", rid)   # 段階3c: _template 由来の room が使えるプレースホルダ
        text = _inject_tabs(rid, text)
        return Resp(200, "text/html; charset=utf-8", versioned_html(text.encode("utf-8")))
    if path in (f"/{rid}.js", f"/{rid}/page.js") and room.file("page.js"):
        r = _static(room, "page.js")
        if r:
            r.headers = dict(r.headers or {}, **{"X-Shell-Version": util.SHELL["version"]})
        return r
    if rest == "tab.js" and room.file("tab.js"):
        r = _static(room, "tab.js")
        if r:
            r.headers = dict(r.headers or {}, **{"X-Shell-Version": util.SHELL["version"]})
        return r
    if rest in ("home.css", "home.js") and room.file(rest):
        r = _static(room, rest)
        if r:
            r.headers = dict(r.headers or {}, **{"X-Shell-Version": util.SHELL["version"]})
        return r
    if rest.startswith("static/"):
        return _static(room, rest)
    return None


# ---------- 定時ジョブ・常駐ワーカー・朝の便り ----------
_last_err = {}


def _due(job, now):
    wd = job.get("weekday")
    if wd is not None and now.tm_wday != wd:
        return False
    if job.get("every") == "minute":
        return True
    h, m = (int(x) for x in str(job["at"]).split(":"))
    return (now.tm_hour, now.tm_min) >= (h, m)


def run_jobs():
    """scheduler から毎分呼ばれる。1つのジョブが落ちても他は回す"""
    now = time.localtime()
    for r in active():
        for job in getattr(r.jobs, "JOBS", []) if r.jobs else []:
            try:
                if _due(job, now):
                    job["fn"]()
            except Exception as e:
                key = f"{r.id}.{job.get('name')}"
                if _last_err.get(key) != str(e):
                    _last_err[key] = str(e)
                    traceback.print_exc()


def start_workers():
    for r in active():
        for fn in getattr(r.jobs, "START", []) if r.jobs else []:
            threading.Thread(target=fn, daemon=True, name=f"room-{r.id}").start()


def brief_sections(day):
    """全 room の BRIEF を集めて order 順に返す"""
    out = []
    for r in active():
        fn = getattr(r.jobs, "BRIEF", None) if r.jobs else None
        if not fn:
            continue
        try:
            out += [dict(s, room=r.id) for s in (fn(day) or [])]
        except Exception as e:
            out.append({"order": 999, "lines": [f"- {r.id}: 読めませんでした({type(e).__name__})"], "room": r.id})
    return sorted(out, key=lambda s: s.get("order", 100))


# ---------- ジョブの二重実行よけ(log/<name>-<day>.done) ----------
def done(name):
    return os.path.exists(os.path.join(C.LOG_DIR, f"{name}.done"))


def mark_done(name, text=""):
    os.makedirs(C.LOG_DIR, exist_ok=True)
    with open(os.path.join(C.LOG_DIR, f"{name}.done"), "w", encoding="utf-8") as f:
        f.write(text)
