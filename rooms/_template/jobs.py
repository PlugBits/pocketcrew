"""メモ室の定時ジョブ・朝の便りの例。実際に使わないなら JOBS も BRIEF も空にしてよい
(START は使わないので置いていない。常駐ワーカーが要る room だけ書く)。
"""
import os
import time

from core import rooms
from core import util

_ROOM_ID = os.path.basename(os.path.dirname(os.path.abspath(__file__)))


def _example_job():
    """21:00 を過ぎたら1回だけ動く例(何もしない)。
    "at" のジョブは時刻を過ぎている間ずっと毎分呼ばれるので、二重実行しないように
    rooms.done()/rooms.mark_done() の印(log/<name>-<day>.done)を自分で見る。
    実際に何かを届けたいときは util.notify(title, body, url, tag) で push を送る。"""
    day = time.strftime("%Y-%m-%d")
    key = f"{_ROOM_ID}-example-{day}"
    if rooms.done(key):
        return
    # ここに本来やりたい処理を書く。例えば:
    #   util.notify("メモ", "今日はここまで", f"/{_ROOM_ID}", "memo-example")
    rooms.mark_done(key, f"{day} 21:00 の例のジョブ(何もしない)")


JOBS = [
    {"name": "example", "at": "21:00", "fn": _example_job},
]


def _brief(day):
    """朝の便りに足す1段。day は "YYYY-MM-DD"。返り値が空リストならその日は何も出さない"""
    rel = rooms.room_config(_ROOM_ID).get("file", f"{_ROOM_ID}/log.md")
    path = util.safe_path(rel)
    count = 0
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            count = sum(1 for line in f if line.startswith(f"- {day}"))
    return [{"order": 50, "lines": ["## メモ", f"- 今日の追加: {count}件"]}]


BRIEF = _brief
