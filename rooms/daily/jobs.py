"""定時ジョブ: 日次まとめ(21:30)・朝の便り(07:30)。BRIEF には「昨日のまとめ」「常駐機」の2段を出す。
本体は daily_brief.py(朝の便りの組み立て)と core/collect.py(日次まとめ・材料集め)。"""
import os
import sys
import time

_ROOT = os.path.dirname(os.path.realpath(__file__))
while not os.path.isdir(os.path.join(_ROOT, "core")):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import config as C
from core import collect
from daily_brief import morning_brief

# 日次まとめの再試行スロットル(旧 core/server.py scheduler() の last_try と同じ、10分おきに再試行)
_last_try = {"t": 0.0}


def _daily_summary_job():
    if time.time() - _last_try["t"] < 600:
        return
    r = collect.daily_summary()
    if not r.get("skipped"):
        _last_try["t"] = time.time()


def BRIEF(day):
    y_day, y_items = collect.yesterday_highlights()
    yesterday_lines = ["## 昨日のまとめ"]
    yesterday_lines += [f"- {n}: {t}" for n, t in y_items] if y_items else [f"- {y_day} のまとめはありません"]

    sess = collect.sessions()
    stopped = [s["name"] for s in sess if not s["pid"]]
    with open("/proc/uptime") as f:
        up_h = int(float(f.read().split()[0]) // 3600)
    uptime_lines = ["## 常駐機", f"- 稼働 {up_h}h・{len(sess)}スレ・停止: {'、'.join(stopped) if stopped else 'なし'}"]

    return [
        {"order": 30, "lines": yesterday_lines},
        {"order": 90, "lines": uptime_lines},
    ]


JOBS = [
    {"name": "brief", "at": f"{C.BRIEF_HOUR:02d}:{C.BRIEF_MIN:02d}", "fn": morning_brief},
    {"name": "daily-summary", "at": f"{C.DAILY_HOUR:02d}:{C.DAILY_MIN:02d}", "fn": _daily_summary_job},
]
