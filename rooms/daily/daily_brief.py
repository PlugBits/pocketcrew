"""朝の便り(vault/daily/brief-YYYY-MM-DD.md)の組み立て。
各 room の BRIEF(day) を core.rooms.brief_sections() で集めて1本の本文にする(元は core/server.py の morning_brief)。"""
import datetime
import os
import sys

_ROOT = os.path.dirname(os.path.realpath(__file__))
while not os.path.isdir(os.path.join(_ROOT, "core")):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core import rooms, util
from core import collect


def morning_brief(force=False):
    """毎日07:30(ローカル)に1回。各 room の BRIEF を集めてvaultへ保存し、Web Push 1通。
    二重送信は log/brief-YYYY-MM-DD.done で防ぐ。"""
    day = collect.now().strftime("%Y-%m-%d")
    mark = os.path.join(collect.LOG_DIR, f"brief-{day}.done")
    if os.path.exists(mark) and not force:
        return {"ok": True, "skipped": "already done"}

    sections = rooms.brief_sections(day)
    lines = []
    for s in sections:
        if lines and not s.get("join"):
            lines.append("")
        lines += s["lines"]
    body_md = "\n".join(lines) + "\n"

    os.makedirs(collect.VAULT_DAILY, exist_ok=True)
    path = os.path.join(collect.VAULT_DAILY, f"brief-{day}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"---\ndate: {day}\ntype: brief\n---\n\n# 朝の便り {day}\n\n" + body_md)

    wd = "月火水木金土日"[datetime.date.fromisoformat(day).weekday()]
    title = f"おはようございます {day.replace('-', '/')}({wd})"
    push_body = " · ".join(s["push"] for s in sections if s.get("push"))[:120]
    push_res = util.notify(title, push_body, "/plan", "brief")

    os.makedirs(collect.LOG_DIR, exist_ok=True)
    with open(mark, "w", encoding="utf-8") as f:
        f.write(collect.now().isoformat(timespec="seconds"))
    collect.log_action("brief", day=day)
    return {"ok": True, "path": path, "title": title, "body": push_body, "push": push_res}
