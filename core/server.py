#!/usr/bin/env python3
"""ポケクル(Pocket Crew): 常駐機の司令室(core。段階C: room に移せる機能は全部 rooms/・rooms-private/ へ出した)。
/            画面
/api/status  マシン指標 + セッション一覧(3秒キャッシュ)
/api/rooms   room の一覧・⋯メニュー・読み込み時の警告
/api/pane?w=<window>  そのセッションの画面末尾200行
POST /api/send {window,text,enter}  tmux send-keys(v1)
POST /api/ask {text,window?,timeout?} → {reply}  Siri ショートカット用(送って待って返す)
POST /api/key {window,key} / /api/new {name} / /api/restart {window}  (v2)
POST /api/choice {window,option}  AskUserQuestion のピッカーで選択肢を1つ選ぶ(数字キー1つだけ。
Enter は送らない。理由は core/collect.py の parse_choice() のコメント参照。2026-09-27)
/api/file?p= /api/img?p=  ~/vault の読み取り(閲覧のみ。note・numbers 等の他 room も直接叩く汎用経路)。
ディレクトリ一覧(旧 /api/ls)は vault UI 専用だったので rooms/vault/api.py へ移した(GET /api/ls のまま動く)。
POST /api/inquiry {kind,text,...} → {job} を即返す非同期ジョブ(sync:trueで同期)。room 共有の裸パス
(docs の add/ask/rewrite/fix、その他 room 固有の kind)。本体は core/jobs.py(api_inquiry・
normalize_inquiry_body・access_log)。kind ごとの検証+ジョブ作成は各 room が jobs.register(accept=...)
で登録する(core/jobs.py の docstring参照)。
GET /api/inquiry/<job> で結果を取る / GET /api/inquiry/recent?kind=ask&n=
/<room>, /<room>.js, /<room>/tab.js, /api/<room>/... は core/rooms.py が room を読み込んで配る
(このファイルは触らない。room 側の変更は rooms/・rooms-private/ 配下だけで完結する)。
待ち受けは Tailscale の IP と localhost のみ(TINY_PULSE_BIND で変更可)。"""
import hashlib
import html
import json
import os
import re
import time
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from core import config as C
from core import util
from core import rooms
from core import jobs
from core import collect
from core import update
try:
    from core import webpush
except Exception:   # cryptography が無い環境でも司令室自体は動かす
    webpush = None

CERT_DIR = C.CERT_DIR
HTTPS_PORT = C.HTTPS_PORT
HOSTNAME = C.HOSTNAME

VAULT = util.VAULT
safe_path = util.safe_path      # 実装は core/util.py(room と共通)。呼び出し側はそのまま
INBOX = C.INBOX
UPLOAD_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".pdf", ".txt", ".md", ".csv", ".json"}
MAX_UPLOAD = 20_000_000


def save_upload(name: str, data: bytes):
    """iPhone から送られたファイルを inbox に保存し、セッションに渡す絶対パスを返す"""
    import re as _re, datetime as _dt
    base = os.path.basename(name or "file")
    ext = os.path.splitext(base)[1].lower()
    if ext not in UPLOAD_EXT:
        return {"ok": False, "error": f"type not allowed: {ext or '(none)'}"}
    if len(data) > MAX_UPLOAD:
        return {"ok": False, "error": "too large (20MB)"}
    stem = _re.sub(r"[^\w\-]+", "_", os.path.splitext(base)[0])[:40] or "file"
    os.makedirs(INBOX, exist_ok=True)
    path = os.path.join(INBOX, f"{_dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{stem}{ext}")
    with open(path, "wb") as f:
        f.write(data)
    return {"ok": True, "path": path, "size": len(data)}


def cleanup_inbox(days=7):
    try:
        cutoff = time.time() - days * 86400
        for n in os.listdir(INBOX):
            p = os.path.join(INBOX, n)
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                os.remove(p)
    except OSError:
        pass


TEXT_EXT = {".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".jsonl"}
MAX_FILE = 1_000_000
# 画像(2026-09-21)。画面のリンクは png/jpg/webp もリンクにしているのに api_file() が
# TEXT_EXT しか返さず「no such file」になっていた。画像は別の経路(/api/img)で出す。
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif"}
MAX_IMAGE = 10 * 1024 * 1024


# api_ls(/api/ls: vault のディレクトリ一覧)は vault UI 専用だったので rooms/vault/api.py へ移した
# (段階: vault を公開サンプルの room にする)。api_file・api_img は note・numbers 等の他 room も
# HTTP 経由で直接叩く汎用の vault 読み取り経路なので、ここ(core)に残す。


def api_img(rel):
    """画像を返す(2026-09-21)。api_file() とは別の経路。safe_path() の制限
    (~/vault の外と隠しファイルは拒否)はそのまま使う。戻りは (mime, bytes) か (None, 理由)。"""
    f = safe_path(rel)
    if not f or not os.path.isfile(f):
        return None, "no such file"
    mime = IMAGE_TYPES.get(os.path.splitext(f)[1].lower())
    if not mime:
        return None, "not an image"
    if os.path.getsize(f) > MAX_IMAGE:
        return None, "too large"
    with open(f, "rb") as fh:
        return mime, fh.read()


def api_pimg(p):
    """スレの本文に出た画像のパスを返す(2026-09-27)。~/… か絶対パスを受け、実体(symlink 解決後)が
    C.IMAGE_ROOTS のどれかの中・隠しフォルダ(.git/.claude 等)を通らない・拒否リストの名前を通らない・
    画像の拡張子、のときだけ返す。鍵や名簿は画像の拡張子でないので、ここからは出ない。"""
    raw = (p or "").strip()
    if not raw.startswith(("~/", "/")):
        return None, "bad path"
    real = os.path.realpath(os.path.expanduser(raw))
    root = next((r for r in C.IMAGE_ROOTS if real == r or real.startswith(r.rstrip(os.sep) + os.sep)), None)
    if not root:
        return None, "not allowed"
    parts = [x for x in os.path.relpath(real, root).split(os.sep) if x]
    if any(x.startswith(".") or x in C.IMAGE_DENY_PARTS for x in parts):
        return None, "not allowed"
    mime = IMAGE_TYPES.get(os.path.splitext(real)[1].lower())
    if not mime:
        return None, "not an image"
    if not os.path.isfile(real):
        return None, "no such file"
    if os.path.getsize(real) > MAX_IMAGE:
        return None, "too large"
    with open(real, "rb") as fh:
        return mime, fh.read()


def api_file(rel):
    f = safe_path(rel)
    if not f or not os.path.isfile(f) or os.path.splitext(f)[1].lower() not in TEXT_EXT:
        return {"ok": False, "error": "no such file"}
    if os.path.getsize(f) > MAX_FILE:
        return {"ok": False, "error": "too large"}
    with open(f, encoding="utf-8", errors="replace") as fh:
        return {"ok": True, "path": os.path.relpath(f, VAULT), "text": fh.read(), "mtime": int(os.path.getmtime(f))}


# ---------- POST/GET /api/inquiry(裸パス。room 共有。core/jobs.py が本体) ----------
def api_inquiry_get(job_id):
    job = jobs.get(job_id)
    if not job:
        return {"ok": False, "error": "no such job"}
    out = {"ok": True, "job": job["id"], "kind": job["kind"], "status": job["status"], "created": job.get("created")}
    if job.get("finished"):
        out["finished"] = job["finished"]
    if job["status"] == "done":
        out["result"] = job.get("result")
    elif job["status"] == "failed":
        out["error"] = job.get("error")
        if job.get("result"):
            out["result"] = job.get("result")
    return out


def api_inquiry_recent(qs):
    kind = qs.get("kind", ["ask"])[0]
    try:
        n = max(1, min(20, int(qs.get("n", ["3"])[0])))
    except ValueError:
        n = 3
    out = []
    for j in jobs.recent(kind, n):
        r = j.get("result") or {}
        out.append({"job": j["id"], "text": (j.get("text") or "").splitlines()[0][:200] if j.get("text") else "",
                    "draft": r.get("draft", ""), "answer": r.get("answer", ""), "sources": r.get("sources", []),
                    "finished": j.get("finished")})
    return {"ok": True, "items": out}


HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # リポジトリ直下(root shim 用)
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")   # core/static(index.html, sw.js, manifest.json, icon-*)

# シェル版はファイル内容から自動算出する(手で上げ忘れて古い資産が配られる事故を防ぐ)。
# サーバ起動のたびに再計算する(編集後は毎回再起動される運用のため)。room の資産(rooms.asset_files())
# も合わせてハッシュに含める(room 側の更新でもシェル版が上がるように)。core 固有のファイルは
# index.html・sw.js・manifest.json・theme.css・theme.js(他は全部 room 側が room.json の "assets" で持つ)。
# theme.css/theme.js は全ページ共有の配色(2026-09-27 ライトテーマ。core/static/theme.css 参照)。
SHELL_ASSET_FILES = [
    os.path.join(STATIC_DIR, "index.html"),
    os.path.join(STATIC_DIR, "sw.js"),
    os.path.join(STATIC_DIR, "manifest.json"),
    os.path.join(STATIC_DIR, "theme.css"),
    os.path.join(STATIC_DIR, "theme.js"),
]
# index.html 等が参照する script タグに ?v= を付けて配信時に書き換える処理は core/util.py に1本化
# (room はそちらの util.versioned_html() を使う)。
_versioned_html = util._versioned_html


def compute_shell_version():
    h = hashlib.sha256()
    for path in SHELL_ASSET_FILES + rooms.asset_files():
        try:
            with open(path, "rb") as f:
                h.update(f.read())
        except OSError:
            continue
    return f"{time.strftime('%Y-%m-%d')}-{h.hexdigest()[:8]}"


# sw.js のキャッシュ対象(SHELL 配列)。core 固定分(index.html自身とアイコン類)+ room 側
# (rooms.shell_paths(): room.json の "cache" も含む)を足して重複を消す。
_CORE_SHELL = ['/', '/manifest.json', '/icon-192.png', '/icon-512.png', '/theme.css', '/theme.js']


def compute_shell_list():
    seen = []
    for p in _CORE_SHELL + rooms.shell_paths():
        if p not in seen:
            seen.append(p)
    return seen


# sw.js が「毎回サーバー側で描画する動的ページ(個人データを含みうる)」として常にネットワーク優先で
# 扱うパス。core 固定分(ホームと dashboard)+ room 側(rooms.dynamic_paths(): room.json の "cache" の
# うち拡張子無しのもの)を足して重複を消す。
_CORE_DYNAMIC = ['/', '/plan', '/home']


def compute_dynamic_list():
    seen = []
    for p in _CORE_DYNAMIC + rooms.dynamic_paths():
        if p not in seen:
            seen.append(p)
    return seen


rooms.load_all()   # 起動前・import 時点で読み込む(スレッドは起こさない。テストの import core.server でも安全)
SHELL_VERSION = compute_shell_version()
util.SHELL["version"] = SHELL_VERSION   # room が util.versioned_html() で使う
PORT = C.PORT
BIND = C.BIND
_cache = util.STATUS_CACHE   # 実体は core/util.py 側(util.invalidate_status() と共有)
_lock = threading.Lock()

STATUS_TTL = 1.5


def status():
    with _lock:
        if time.time() - _cache["t"] > STATUS_TTL:
            data = collect.collect()
            data["update"] = update.state()
            data["features"] = {"jobs": C.JOBS_ENABLED, "auto_restore": C.AUTO_RESTORE, "push": C.PUSH_ENABLED}
            data["room_warnings"] = rooms.warnings()
            _cache["data"] = data
            _cache["t"] = time.time()
        return _cache["data"]


# ⋯メニュー(#homeMenu)の room 差し込み。room がまだ無い(rooms.menu() が空)間は index.html の
# 元のボタン(plan/note/workout/num/newthread)をそのまま出す(段階的移行で退行させないため)。
# room が出てきたら、core固定の新しいスレ(order 900)と order でマージして並べ直す。
# vault(📁 vault・order 30)は core固定ではなく rooms/vault/room.json の "menu" が持つ
# (段階: vault を公開サンプルの room にする。無効化すればこの項目も自然に消える)。
# 2026-09-27: 末尾の検出は次の兄弟(#threadMenu)手前までの lookahead にした(非貪欲の
# ".*?(</div></div>)" のままだと、間に挟む要素(配色の選択行など)が入れ子の </div></div> を
# 含むと、そこで早期に一致して閉じるボタンより後ろが宙に浮いていた。実機で確認)。
_HOME_MENU_RE = re.compile(r'(<div id="homeMenu" class="menu"><div class="sheet">).*?(</div></div>)(?=\s*<div id="threadMenu")', re.S)


def _home_menu_html():
    items = list(rooms.menu())
    items.append({"order": 900, "label": "+ 新しいスレを立てる", "act": "newthread"})
    items.sort(key=lambda x: x["order"])
    parts = []
    for it in items:
        label = html.escape(it.get("label", ""))
        if it.get("act"):
            parts.append(f'<button data-act="{it["act"]}">{label}</button>')
        else:
            href = html.escape(it.get("href", ""), quote=True)
            parts.append(f'<button data-href="{href}">{label}</button>')
    # 配色の選択(2026-09-27)。ホームの ⋯ メニューだけに出す(要件参照)。room 一覧とは無関係に
    # 常に足す(core/static/theme.js が data-theme-opt のクリックを拾う。localStorage は共通)。
    parts.append(
        '<div class="theme-row" id="themeRow"><span class="theme-row-label">表示</span>'
        '<div class="theme-row-opts">'
        '<button type="button" data-theme-opt="auto">端末に合わせる</button>'
        '<button type="button" data-theme-opt="light">ライト</button>'
        '<button type="button" data-theme-opt="dark">ダーク</button>'
        '</div></div>'
    )
    parts.append('<button class="cancel" data-act="close">閉じる</button>')
    return "".join(parts)


def _inject_home_menu(html_bytes):
    if not rooms.menu():
        return html_bytes
    text = html_bytes.decode("utf-8")
    text, n = _HOME_MENU_RE.subn(lambda m: m.group(1) + _home_menu_html() + m.group(2), text, count=1)
    if n != 1:
        return html_bytes   # アンカーが見つからなければ元のまま返す(壊れたHTMLを配らない)
    return text.encode("utf-8")


# room.json の "home" キー(home.css/home.js)を index.html に差し込む(core/rooms.py の docstring参照。
# 段階: vault を公開サンプルの room にする)。CSS は <head> の直後、JS はホーム画面の本体 <script>…</script>
# の閉じタグの直後(=core の主スクリプトが実行し終わったあと)に置く。room.json の宣言順・room 順(order,id)。
def _inject_home_assets(html_bytes):
    css, js = rooms.home_assets()
    if not css and not js:
        return html_bytes
    text = html_bytes.decode("utf-8")
    if css:
        tags = "".join(f'<link rel="stylesheet" href="/{rid}/{name}?v={SHELL_VERSION}">' for rid, name in css)
        text = text.replace("<head>", "<head>\n" + tags, 1)
    if js:
        tags = "".join(f'<script src="/{rid}/{name}?v={SHELL_VERSION}"></script>' for rid, name in js)
        text, n = re.subn(r'(</script>)(\s*</body>)', lambda m: m.group(1) + tags + m.group(2), text, count=1)
        if n != 1:
            text += tags   # アンカーが見つからなくても home.js 自体は諦めずに末尾へ足す
    return text.encode("utf-8")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj):
        self._send(200, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode())

    def _send_room(self, r):
        """rooms.route() が返した Resp をそのまま送る(HTML には他のページと同じ X-Shell-Version を足す)"""
        extra = dict(r.headers or {})
        if r.ctype.startswith("text/html"):
            extra.setdefault("X-Shell-Version", SHELL_VERSION)
        self._send(r.code, r.ctype, r.body, extra)

    def _read_body(self, limit):
        """Content-Length か chunked(iOS Safari の fetch はファイル送信で chunked になることがある)の両方を読む"""
        te = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in te:
            buf = bytearray()
            while True:
                line = self.rfile.readline().strip()
                if not line:
                    continue
                size = int(line.split(b";")[0], 16)
                if size == 0:
                    while True:                       # トレーラを読み飛ばす
                        if self.rfile.readline().strip() == b"":
                            break
                    break
                buf += self.rfile.read(size)
                self.rfile.readline()                 # CRLF
                if len(buf) > limit:
                    return None
            return bytes(buf)
        n = int(self.headers.get("Content-Length", "0") or 0)
        if n > limit:
            return None
        return self.rfile.read(n)

    def do_POST(self):
        u = urlparse(self.path)
        # room 側のルートを先に試す。body はまだ何も読んでいない(Req.body() は遅延読み込み)ので、
        # ここで当たらなかった場合に下の既存の分岐が自分で読みに行っても壊れない。
        r = rooms.route(self, "POST", u.path, parse_qs(u.query), self._read_body, util.versioned_html)
        if r is not None:
            self._send_room(r)
            return
        if u.path == "/api/upload":
            data = self._read_body(MAX_UPLOAD)
            if data is None:
                self._json({"ok": False, "error": "too large (20MB)"})
                return
            if not data:
                self._json({"ok": False, "error": "empty body (0 bytes)"})
                return
            name = parse_qs(u.query).get("name", ["file"])[0]
            self._json(save_upload(name, data))
            return
        if u.path == "/api/inquiry":
            raw = self._read_body(2 * 1024 * 1024)
            ct = self.headers.get("Content-Type", "")
            blen = len(raw or b"")
            if not raw:
                res = {"ok": False, "error": "本文が空です。" + jobs.INQUIRY_HELP}
                jobs.access_log(self, 400, ct, 0, note="empty body")
                self._send(400, "application/json; charset=utf-8", json.dumps(res, ensure_ascii=False).encode())
                return
            try:
                body = json.loads(raw)
                if not isinstance(body, dict):
                    raise ValueError("not an object")
            except Exception:
                res = {"ok": False, "error": "本文が JSON として読めません。" + jobs.INQUIRY_HELP}
                jobs.access_log(self, 400, ct, blen, note="bad json", raw=raw)
                self._send(400, "application/json; charset=utf-8", json.dumps(res, ensure_ascii=False).encode())
                return
            res = jobs.api_inquiry(body)
            code = 200 if res.get("ok") else 400
            nb = jobs.normalize_inquiry_body(body)
            jobs.access_log(self, code, ct, blen, kind=str(nb.get("kind", ""))[:10], text=str(nb.get("text", "") or ""),
                            note=(("job " + str(res.get("job"))) if res.get("ok") else str(res.get("error", ""))[:60])
                            + f" photos={len(nb.get('photos') or [])}", raw=raw)
            self._send(code, "application/json; charset=utf-8", json.dumps(res, ensure_ascii=False).encode())
            return
        n = int(self.headers.get("Content-Length", "0") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        if u.path == "/api/clientlog":
            try:
                collect.log_action("client", **{k: str(v)[:300] for k, v in (body or {}).items()})
            except Exception:
                pass
            self._json({"ok": True})
            return
        if u.path == "/api/send":
            by = (str(body.get("by", "")).strip() or "司令室")[:40]
            res = collect.send(str(body.get("window", "")), str(body.get("text", "")), bool(body.get("enter", True)), by=by)
        elif u.path == "/api/key":
            res = collect.send_key(str(body.get("window", "")), str(body.get("key", "")))
        elif u.path == "/api/choice":
            # AskUserQuestion のピッカーで選択肢を1つ選ぶ。数字キー1つだけを送る専用の経路
            # (/api/send を使わない理由は core/collect.py の parse_choice() のコメント参照:
            # 複数質問の画面で、答えていない次の質問が黙って既定値のまま提出される事故になるため)
            by = (str(body.get("by", "")).strip() or "司令室")[:40]
            res = collect.answer_choice(str(body.get("window", "")), body.get("option"), by=by)
        elif u.path == "/api/new":
            res = collect.new_session(str(body.get("name", "")), str(body.get("preset", "")))
        elif u.path == "/api/relaunch":
            res = collect.relaunch_session(str(body.get("window", "")))
        elif u.path == "/api/push/level":
            res = webpush.set_level(str(body.get("level", ""))) if webpush else {"ok": False}
        elif u.path == "/api/restart":
            res = collect.restart_session(str(body.get("window", "")), force=bool(body.get("force")))
        elif u.path == "/api/ask":
            w = str(body.get("window", "") or "main")
            by = (str(body.get("by", "")).strip() or "司令室")[:40]
            res = collect.ask(w, str(body.get("text", "")), int(body.get("timeout", 55)), by=by)
        elif u.path == "/api/push/subscribe":
            res = webpush.subscribe(body.get("subscription") or {}) if webpush else {"ok": False, "error": "webpush unavailable"}
        elif u.path == "/api/push/unsubscribe":
            res = webpush.unsubscribe(str(body.get("endpoint", ""))) if webpush else {"ok": False}
        elif u.path == "/api/push/test":
            res = {"ok": True, "results": webpush.broadcast("ポケクル", "通知テスト。届いていれば設定完了です", "/", "test")} if webpush else {"ok": False}
        elif u.path == "/api/forget":
            res = collect.forget_session(str(body.get("window", "")))
        elif u.path == "/api/draft/send":
            # 入力欄に残った未送信の文をそのまま送る(配達確認つき)
            res = collect.send_draft(str(body.get("window", "")),
                                     by=(str(body.get("by", "")).strip() or "司令室")[:40])
        elif u.path == "/api/draft/clear":
            # 入力欄に残った未送信の文を消す。C-u を使う(Escape は効かないうえ、
            # 作業中に送ると生成を中断して指示を入力欄に戻す。2026-09-23 に実測)
            res = collect.clear_draft(str(body.get("window", "")),
                                      by=(str(body.get("by", "")).strip() or "司令室")[:40])
        elif u.path == "/api/stop":
            # 2026-09-22: 動作中のスレも止める(/api/forget は停止中しか閉じられない)。
            # auto=False → kill-window の順番は collect.stop_session が持つ。
            w = str(body.get("window", ""))
            by = (str(body.get("by", "")).strip() or "司令室")[:40]
            res = collect.stop_session(w, by=by) if w else {"ok": False, "error": "window が要ります"}
        elif u.path == "/api/session/brief":
            res = collect.set_session_brief(str(body.get("window", "")), str(body.get("brief", "")))
        elif u.path == "/api/update/check":
            update.check(force=True)
            res = {"ok": True, **update.state()}
        elif u.path == "/api/update/apply":
            res = update.apply()
        else:
            res = None
        if res is not None:
            _cache["t"] = 0
            self._json(res)
        else:
            self._send(404, "text/plain", b"not found")

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        last = None
        last_sent = 0.0
        try:
            while True:
                js = json.dumps(status(), ensure_ascii=False)
                if js != last:
                    last = js
                    self.wfile.write(f"event: status\ndata: {js}\n\n".encode())
                    self.wfile.flush()
                    last_sent = time.time()
                elif time.time() - last_sent >= 15:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_sent = time.time()
                time.sleep(1.5)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            pass

    def do_GET(self):
        u = urlparse(self.path)
        r = rooms.route(self, "GET", u.path, parse_qs(u.query), self._read_body, util.versioned_html)
        if r is not None:
            self._send_room(r)
            return
        if u.path == "/api/events":
            self._events()
        elif u.path == "/api/status":
            self._json(status())
        elif u.path == "/api/rooms":
            self._json({"rooms": [r.info() for r in rooms.ROOMS.values()], "menu": rooms.menu(), "warnings": rooms.warnings()})
        elif u.path == "/api/file":
            self._json(api_file(parse_qs(u.query).get("p", [""])[0]))
        elif u.path == "/api/pimg":
            # スレの本文の画像パス(2026-09-27)。/api/img と同じく画像そのものを返す
            mime, data = api_pimg(parse_qs(u.query).get("p", [""])[0])
            if not mime:
                self._send(404, "text/plain; charset=utf-8", str(data).encode("utf-8"))
            else:
                self._send(200, mime, data, {"Cache-Control": "private, max-age=300"})
        elif u.path == "/api/img":
            # 画像(2026-09-21)。JSON ではなく画像そのものを返す(画面が <img> で開く)。
            # 長押しの保存とピンチの拡大は、img であればブラウザの標準の動きに任せられる。
            mime, data = api_img(parse_qs(u.query).get("p", [""])[0])
            if not mime:
                self._send(404, "text/plain; charset=utf-8", str(data).encode("utf-8"))
            else:
                self._send(200, mime, data, {"Cache-Control": "private, max-age=60"})
        elif u.path == "/api/pane":
            w = parse_qs(u.query).get("w", [""])[0]
            self._json({"window": w, "text": collect.pane_full(w)})
        elif u.path in ("/", "/index.html"):
            with open(os.path.join(STATIC_DIR, "index.html"), "rb") as f:
                html_bytes = _versioned_html(_inject_home_assets(_inject_home_menu(f.read())), SHELL_VERSION, inject_meta=True)
            self._send(200, "text/html; charset=utf-8", html_bytes, {"X-Shell-Version": SHELL_VERSION})
        elif u.path == "/api/version":
            self._json({"version": SHELL_VERSION})
        elif u.path == "/api/update":
            self._json(update.state())
        elif u.path == "/sw.js":
            with open(os.path.join(STATIC_DIR, "sw.js"), encoding="utf-8") as f:
                b = (f.read().replace("__VERSION__", SHELL_VERSION)
                     .replace("__SHELL__", json.dumps(compute_shell_list(), ensure_ascii=False))
                     .replace("__DYNAMIC__", json.dumps(compute_dynamic_list(), ensure_ascii=False))
                     .encode("utf-8"))
            self.send_response(200); self.send_header("Content-Type", "application/javascript"); self.send_header("Service-Worker-Allowed", "/")
            self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        elif u.path == "/manifest.json":
            with open(os.path.join(STATIC_DIR, "manifest.json"), "rb") as f:
                self._send(200, "application/manifest+json", f.read(), {"X-Shell-Version": SHELL_VERSION})
        elif u.path == "/theme.css":
            # 配色(ライト/ダーク)の共有 CSS。全ページが <link rel="stylesheet" href="/theme.css?v=..."> で読む
            # (2026-09-27 ライトテーマ。core/static/theme.css 参照。?v= は core/util.py の _versioned_html が付ける)。
            with open(os.path.join(STATIC_DIR, "theme.css"), "rb") as f:
                self._send(200, "text/css; charset=utf-8", f.read(), {"X-Shell-Version": SHELL_VERSION})
        elif u.path == "/theme.js":
            # 配色の切り替えロジック(⋯メニュー配線・端末配色への追従)。core/static/theme.js 参照
            with open(os.path.join(STATIC_DIR, "theme.js"), "rb") as f:
                self._send(200, "application/javascript; charset=utf-8", f.read(), {"X-Shell-Version": SHELL_VERSION})
        elif u.path in ("/icon.svg", "/icon-192.png", "/icon-512.png"):
            fp = os.path.join(STATIC_DIR, u.path.lstrip("/"))
            if os.path.exists(fp):
                extra = {"X-Shell-Version": SHELL_VERSION} if u.path in ("/icon-192.png", "/icon-512.png") else None
                with open(fp, "rb") as f:
                    self._send(200, "image/svg+xml" if fp.endswith(".svg") else "image/png", f.read(), extra)
            else:
                self._send(404, "text/plain", b"no icon")
        elif u.path == "/api/past":
            self._json({"ok": True, "past": collect.past_sessions()})
        elif u.path == "/api/session/brief":
            self._json(collect.get_session_brief(parse_qs(u.query).get("window", [""])[0]))
        elif u.path == "/api/presets":
            self._json({"ok": True, "presets": list(collect.load_presets().keys())})
        elif u.path == "/api/log":
            day = parse_qs(u.query).get("d", [time.strftime("%Y-%m-%d")])[0]
            self._json({"ok": True, "day": day, "items": collect.read_log(day)})
        elif u.path == "/api/push/key":
            self._json({"ok": bool(webpush), "key": webpush.public_key() if webpush else "", "subs": len(webpush.subscriptions()) if webpush else 0, "level": webpush.get_level() if webpush else "", "shell": SHELL_VERSION,
                        "https": os.path.exists(os.path.join(CERT_DIR, "fullchain.pem")), "host": HOSTNAME, "port": HTTPS_PORT})
        elif u.path == "/api/inquiry":
            jobs.access_log(self, 400, note="GET not allowed")
            self._send(400, "application/json; charset=utf-8", json.dumps(
                {"ok": False, "error": "GET は受け付けません。" + jobs.INQUIRY_HELP}, ensure_ascii=False).encode())
        elif u.path == "/api/inquiry/recent":
            jobs.access_log(self, 200, note="recent")
            self._json(api_inquiry_recent(parse_qs(u.query)))
        elif u.path.startswith("/api/inquiry/"):
            jobs.access_log(self, 200, note="job status")
            self._json(api_inquiry_get(u.path[len("/api/inquiry/"):]))
        elif u.path.startswith("/api/jobs/"):
            # /api/inquiry/<id> の別名(段階A2: room 共有のジョブキューが core に一本化された
            # ことに合わせて、docs 専用でない呼び名を用意)。ハンドラは同じ。
            jobs.access_log(self, 200, note="job status")
            self._json(api_inquiry_get(u.path[len("/api/jobs/"):]))
        else:
            self._send(404, "text/plain", b"not found")


def scheduler():
    """毎分: 名簿からの復帰・inbox掃除・Claude更新の確認(6時間キャッシュ)・証明書更新(日次)。
    JOBS_ENABLED のときはさらに: 更新通知・ログイン期限チェック(09:00以降1日1回)・
    room 側の定時ジョブ(rooms.run_jobs())。日次まとめ・朝の便り・期限リマインド・数字取得・
    お得の網・カード等、各機能の定時処理は該当 room の jobs.py に移った(段階3)。"""
    while True:
        try:
            collect.ensure_window_size()
            if C.AUTO_RESTORE:
                collect.restore_sessions()
            cleanup_inbox()
            update.check()
            if int(time.time()) % 86400 < 60:
                ensure_cert()
            if C.JOBS_ENABLED:
                update.notify_available()
                now = time.localtime()
                if now.tm_hour >= C.LOGIN_CHECK_HOUR:
                    login_expiry_check()
                rooms.run_jobs()   # 各 room の定時ジョブ・朝の便りの段はここから毎分呼ばれる
        except Exception:
            pass
        time.sleep(60)


LOGIN_WARN_DAYS = 3


def login_expiry_days():
    """Claude のログイン(リフレッシュトークン)の残り日数。トークン本体は読まず期限だけ取り出す。不明なら None"""
    try:
        with open(C.CLAUDE_CREDENTIALS, encoding="utf-8") as f:
            exp_ms = json.load(f).get("claudeAiOauth", {}).get("refreshTokenExpiresAt")
        if not exp_ms:
            return None
        return (exp_ms / 1000 - time.time()) / 86400
    except Exception:
        return None


def login_expiry_check(force=False):
    """09:00 以降に1日1回: ログイン期限が LOGIN_WARN_DAYS 日以内なら Push で知らせる。
    2026-09-20 に期限切れで常駐スレ全部が一斉に止まり、iPhone のアプリから消えた(原因が分かるまで時間がかかった)。
    二重送信は log/login-expiry-YYYY-MM-DD.done で防ぐ。"""
    day = collect.now().strftime("%Y-%m-%d")
    mark = os.path.join(collect.LOG_DIR, f"login-expiry-{day}.done")
    if os.path.exists(mark) and not force:
        return {"ok": True, "skipped": "already done"}
    days = login_expiry_days()
    if days is None or days > LOGIN_WARN_DAYS:
        with open(mark, "w") as f:
            f.write(collect.now().isoformat())
        return {"ok": True, "skipped": "not due", "days": days}
    exp_ms = None
    try:
        with open(C.CLAUDE_CREDENTIALS, encoding="utf-8") as f:
            exp_ms = json.load(f).get("claudeAiOauth", {}).get("refreshTokenExpiresAt")
    except Exception:
        pass
    when = time.strftime("%m/%d %H:%M", time.localtime(exp_ms / 1000)) if exp_ms else "?"
    title = "Claude のログイン期限"
    body = (f"期限切れです({when})。" if days < 0 else f"あと{max(days, 0):.1f}日({when})で切れます。") + \
        "切れると常駐スレが全部止まります。常駐機のターミナルで claude → /login → 各カードの「再起動」"
    push_res = webpush.broadcast(title, body, "/", f"login-expiry-{day}") if (webpush and webpush.subscriptions()) else []
    collect.log_action("login-expiry", days=round(days, 2), when=when, pushed=len(push_res))
    with open(mark, "w") as f:
        f.write(collect.now().isoformat())
    return {"ok": True, "days": days, "when": when, "pushed": len(push_res)}


def notifier():
    """15秒ごとに状態遷移を見て Web Push"""
    while True:
        try:
            if C.PUSH_ENABLED and webpush and webpush.subscriptions():
                lv = webpush.get_level()
                for title, body, tag, w in collect.notify_check(status()["sessions"]):
                    kind = tag.split("-")[0]   # need / done / dead / gone
                    if lv == "need" and kind != "need":
                        continue
                    if lv == "done" and kind not in ("need", "done"):
                        continue
                    webpush.broadcast(title, body, f"/#t={w}", f"{tag}-{int(time.time())}")   # タグは毎回ユニーク(同タグの置き換えを避ける)
                    collect.log_action("notify", title=title, body=body, window=w)
            else:
                collect.notify_check(status()["sessions"])   # 購読が無くても状態は追いかけておく
        except Exception:
            pass
        time.sleep(15)


def ensure_cert():
    """Tailscale の証明書を取得・更新(operator 設定済みなら sudo 不要)。30日未満で更新。
    HOSTNAME が空(config の hostname 未設定)なら何もしない"""
    if not HOSTNAME:
        return True, "no hostname"
    import subprocess, ssl as _ssl, datetime
    os.makedirs(CERT_DIR, exist_ok=True)
    crt, key = os.path.join(CERT_DIR, "fullchain.pem"), os.path.join(CERT_DIR, "privkey.pem")
    need = True
    if os.path.exists(crt):
        try:
            from cryptography import x509
            with open(crt, "rb") as f:
                exp = x509.load_pem_x509_certificate(f.read()).not_valid_after_utc
            need = (exp - datetime.datetime.now(datetime.timezone.utc)).days < 30
        except Exception:
            need = True
    if need:
        r = subprocess.run(["tailscale", "cert", "--cert-file", crt, "--key-file", key, HOSTNAME], capture_output=True, text=True, timeout=120)
        return r.returncode == 0, (r.stderr or r.stdout)[-300:]
    return True, "valid"


def serve_https():
    if not HOSTNAME:
        return
    import ssl
    crt, key = os.path.join(CERT_DIR, "fullchain.pem"), os.path.join(CERT_DIR, "privkey.pem")
    if not (os.path.exists(crt) and os.path.exists(key)):
        return
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(crt, key)
    srv = ThreadingHTTPServer((BIND, HTTPS_PORT), H)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    srv.serve_forever()


def serve(bind):
    ThreadingHTTPServer((bind, PORT), H).serve_forever()


def main():
    if BIND != "127.0.0.1":   # bind が 127.0.0.1 のときは下の serve(BIND) と同じポートになり、起動時に落ちる
        threading.Thread(target=serve, args=("127.0.0.1",), daemon=True).start()
    try:
        collect.ensure_window_size()
        collect.ensure_default_briefs()
    except Exception:
        pass
    threading.Thread(target=scheduler, daemon=True).start()
    threading.Thread(target=notifier, daemon=True).start()
    threading.Thread(target=jobs.worker, daemon=True).start()
    rooms.start_workers()   # room 側の常駐ワーカー(jobs.py の START)
    try:
        ok, msg = ensure_cert()
    except Exception:
        ok = False
    threading.Thread(target=serve_https, daemon=True).start()
    serve(BIND)


if __name__ == "__main__":
    main()
