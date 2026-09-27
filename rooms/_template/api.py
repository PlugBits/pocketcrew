"""メモ室の API。

  GET  /api/<room>       一覧を返す({"items": [...]})。新しい行が先頭に来るよう並べ替える
  POST /api/<room>/add   1行追記する({"text": "..."})

保存先は vault の中の1つの Markdown ファイル。room.json ではなく config.toml の
[rooms.<room>] file = "..." で変えられる(既定は "<room id>/log.md")。

room id はフォルダ名からそのまま取る(os.path.basename)ので、このファイルは
rooms/_template だけでなく、コピーしてできた rooms/reading などでもそのまま動く。
"""
import os
import time

from core import rooms
from core import util

_ROOM_ID = os.path.basename(os.path.dirname(os.path.abspath(__file__)))


def _file_path():
    """保存先の絶対パス。vault の外を指す設定でも util.safe_path が弾いて None を返す"""
    rel = rooms.room_config(_ROOM_ID).get("file", f"{_ROOM_ID}/log.md")
    return util.safe_path(rel)


def get_list(req):
    path = _file_path()
    if not path or not os.path.isfile(path):
        return {"items": []}
    with open(path, encoding="utf-8") as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]
    lines.reverse()   # 新しい行を上に見せる(ファイル上は末尾に追記していく)
    return {"items": lines}


def add(req):
    text = str(req.json().get("text") or "").strip()
    if not text:
        return {"ok": False, "error": "text が空です"}
    path = _file_path()
    if not path:
        return {"ok": False, "error": "保存先が不正です(config.toml の file 設定を確認)"}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"- {stamp} {text}\n")
    util.invalidate_status()   # このメモを /api/status などが見ているわけではないが、
                                # 何かを書いた直後は呼んでおく決まり(他の room もそうしている)
    return {"ok": True}


ROUTES = {"GET /": get_list, "POST /add": add}
