"""room から使う共通ヘルパー(core と room を繋ぐ薄い層)。

room は `from core import config, collect, util` だけを使う(room 同士は import しない)。
ここにある実装が本体(server.py は同じロジックを名前だけ変えて再利用する。二重実装はしない)。

  safe_path(rel), VAULT              vault の外・隠しファイルを拒む読み取りガード
  versioned_html(html_bytes, inject_meta=False)
                                      room のページ配信で script src="/xxx.js" に ?v=<SHELL_VERSION> を付ける
  notify(title, body, url, tag)      webpush があって購読があれば配る(無ければ何もしない)
  invalidate_status()                次の /api/status で作り直させる(server の状態キャッシュを無効化)
  log_action(...)                    collect.log_action の再エクスポート
"""
import os
import re

from core import config as C

VAULT = C.VAULT


def safe_path(rel: str):
    """~/vault の外・隠しファイルは拒否。symlink も実体で判定"""
    rel = (rel or "").strip("/")
    if any(part.startswith(".") for part in rel.split("/") if part):
        return None
    real = os.path.realpath(os.path.join(VAULT, rel))
    if real != VAULT and not real.startswith(VAULT + os.sep):
        return None
    return real


# ---------- シェル版(SHELL_VERSION)によるスクリプトのキャッシュ破棄 ----------
# server.py が起動時に SHELL["version"] へ計算済みの SHELL_VERSION を入れる。
SHELL = {"version": ""}

# 後方互換の既定4本(room が1つも読めていない起動直後などでもこの4本には ?v= を付ける)。
# 段階C: 実際の対象は core.rooms.active() から動的に集める(読み込めた room だけ・page.js/tab.js
# が実在するものだけ)ので、新しい room を足しても ROOM.py 側の変更は要らない。
_VERSIONED_SCRIPTS = ("plan", "docs", "workout", "note")


def _versioned_script_ids():
    """(page.js を持つ room id の集合, tab.js を持つ room id の集合)。core.rooms への依存は
    ここだけに閉じる(rooms.py は util.py を import しないので、循環 import を避けるため遅延 import)。"""
    from core import rooms
    page_ids = set(_VERSIONED_SCRIPTS)
    tab_ids = set()
    for r in rooms.active():
        if r.file("page.js"):
            page_ids.add(r.id)
        if r.file("tab.js"):
            tab_ids.add(r.id)
    return page_ids, tab_ids


def _script_src_re():
    page_ids, tab_ids = _versioned_script_ids()
    parts = [re.escape(n) + r"\.js" for n in sorted(page_ids)]
    parts += [re.escape(n) + r"/tab\.js" for n in sorted(tab_ids)]
    return re.compile(r'src="(/(?:' + "|".join(parts) + r'))"')


def _versioned_html(html_bytes, version, inject_meta=False):
    """script src="/xxx.js"・src="/xxx/tab.js" -> ?v=<version> を配信時に書き換える(ディスク上の
    ファイルは変えない)。対象は読み込めた room の page.js/tab.js を持つ id 全部(旧来の4本を含む)。
    inject_meta=True のときは <head> の直後に <meta name="tp-version"> を差し込む(index.html のみ)。
    server.py の _versioned_html はこの実装をそのまま使う(実体はここ1つだけ)。"""
    text = html_bytes.decode("utf-8")
    text = _script_src_re().sub(lambda m: f'src="{m.group(1)}?v={version}"', text)
    if inject_meta:
        text = text.replace(
            "<head>", f'<head>\n<meta name="tp-version" content="{version}">', 1
        )
    return text.encode("utf-8")


def versioned_html(html_bytes, inject_meta=False):
    """room のページ配信用。バージョンは server が起動時に入れた SHELL["version"] を使う"""
    return _versioned_html(html_bytes, SHELL["version"], inject_meta=inject_meta)


# ---------- /api/status のキャッシュ(server.py と共有する同じ辞書) ----------
STATUS_CACHE = {"t": 0, "data": None}


def invalidate_status():
    """次の /api/status で作り直させる(room が状態を変えた直後などに呼ぶ)"""
    STATUS_CACHE["t"] = 0


# ---------- 通知 ----------
try:
    from core import webpush as _webpush
except Exception:   # cryptography が無い環境でも core は動く
    _webpush = None


def notify(title, body, url, tag):
    """webpush が使えて購読があれば配る。無ければ何もしない(server.py 各所と同じパターン)"""
    if _webpush and _webpush.subscriptions():
        return _webpush.broadcast(title, body, url, tag)
    return []


# ---------- ログ ----------
from core import collect as _collect  # noqa: E402  (定義を上に置きたいので後置 import)

log_action = _collect.log_action
