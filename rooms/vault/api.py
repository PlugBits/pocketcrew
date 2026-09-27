"""vault の見出し(公開サンプル room)。iPhone から ~/vault の Markdown を読んでタップでリンクを
辿れる、をそのまま体験してもらうための room。ホーム画面への差し込みは home.css/home.js
(room.json の "home" キー。core/rooms.py の docstring参照)。この api.py はディレクトリ一覧
(旧 /api/ls)だけを持つ。

  GET /api/vault/ls?p=   ~/vault 配下の一覧({"ok","path","dirs","files"})
  LEGACY: GET /api/ls?p= が同じ実体(旧パスのまま home.js から叩かれる)

ファイル本体(/api/file)と画像(/api/img)は note・numbers 等の他 room も HTTP 経由で直接使う
汎用の vault 読み取り経路なので、あえて core(core/server.py)に残したまま動かす
(room 同士は依存しない決まりなので、vault はそちらには触らない。TEXT_EXT/IMAGE_TYPES は
core 側と同じ定義をここに複製している)。
"""
import os

from core import util

VAULT = util.VAULT
safe_path = util.safe_path

TEXT_EXT = {".md", ".txt", ".json", ".csv", ".yaml", ".yml", ".jsonl"}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif"}


def api_ls(req):
    rel = req.q("p", "")
    d = safe_path(rel)
    if not d or not os.path.isdir(d):
        return {"ok": False, "error": "no such dir"}
    dirs, files = [], []
    for name in sorted(os.listdir(d), key=str.lower):
        if name.startswith("."):
            continue
        full = os.path.join(d, name)
        if os.path.isdir(full):
            dirs.append(name)
        else:
            ext = os.path.splitext(name)[1].lower()
            if ext not in TEXT_EXT and ext not in IMAGE_TYPES:
                continue          # 読めないものは一覧に出さない
            st = os.stat(full)
            row = {"name": name, "size": st.st_size, "mtime": int(st.st_mtime)}
            if ext in IMAGE_TYPES:
                row["image"] = True      # 画面側が img で開くための印(2026-09-21)
            files.append(row)
    files.sort(key=lambda f: -f["mtime"])
    return {"ok": True, "path": os.path.relpath(d, VAULT).replace(".", "", 1) if d != VAULT else "", "dirs": dirs, "files": files}


ROUTES = {"GET /ls": api_ls}
LEGACY = {"GET /api/ls": "GET /ls"}
