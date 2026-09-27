#!/usr/bin/env python3
"""~/vault/plan/{goals,tasks,schedule}.md を読んで構造化する。書き込みはチェックの付け外しだけ。"""
import os, re, sys, datetime

_ROOT = os.path.dirname(os.path.realpath(__file__))
while not os.path.isdir(os.path.join(_ROOT, "core")):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from core import config as C

PLAN_DIR = C.vault_path("plan")
LOCAL = datetime.datetime.now().astimezone().tzinfo
WD = "月火水木金土日"


def _read(name):
    try:
        with open(os.path.join(PLAN_DIR, name), encoding="utf-8") as f:
            return f.read().split("\n")
    except OSError:
        return []


def _strip_fm(lines):
    if lines and lines[0].strip() == "---":
        try:
            j = lines.index("---", 1)
            return lines[j + 1:], j + 1
        except ValueError:
            pass
    return lines, 0


def goals():
    lines, off = _strip_fm(_read("goals.md"))
    out, cur = [], None
    for l in lines:
        m = re.match(r"^##\s+(.*)", l)
        if m:
            cur = {"title": m.group(1).strip(), "due": "", "metric": "", "now": "", "progress": None, "memo": ""}
            out.append(cur)
            continue
        if not cur:
            continue
        for key, field in (("期限", "due"), ("指標", "metric"), ("現在", "now"), ("進捗", "progress"), ("メモ", "memo")):
            m = re.match(rf"^{key}\s*[:：]\s*(.*)", l)
            if m:
                v = m.group(1).strip()
                if field == "progress":
                    d = re.search(r"\d+", v)
                    v = int(d.group()) if d else None
                cur[field] = v
    return out


def tasks():
    lines, off = _strip_fm(_read("tasks.md"))
    out, proj = [], ""
    for i, l in enumerate(lines):
        m = re.match(r"^##\s+(.*)", l)
        if m:
            proj = m.group(1).strip()
            continue
        m = re.match(r"^(\s*)- \[( |x|X)\]\s+(.*)", l)
        if not m:
            continue
        text = m.group(3)
        due = re.search(r"@due\(([\d-]+)\)", text)
        who = re.search(r"@who\(([^)]+)\)", text)
        clean = re.sub(r"\s*@(due|who)\([^)]*\)", "", text).strip()
        out.append({"line": off + i, "project": proj, "done": m.group(2) != " ", "text": clean,
                    "due": due.group(1) if due else "", "who": who.group(1) if who else ""})
    return out


def toggle_task(line: int):
    path = os.path.join(PLAN_DIR, "tasks.md")
    with open(path, encoding="utf-8") as f:
        lines = f.read().split("\n")
    if not 0 <= line < len(lines):
        return {"ok": False, "error": "bad line"}
    l = lines[line]
    if re.match(r"^\s*- \[ \]", l):
        lines[line] = re.sub(r"\[ \]", "[x]", l, 1)
    elif re.match(r"^\s*- \[(x|X)\]", l):
        lines[line] = re.sub(r"\[(x|X)\]", "[ ]", l, 1)
    else:
        return {"ok": False, "error": "not a task line"}
    # updated: を今日に
    today = datetime.datetime.now(LOCAL).strftime("%Y-%m-%d")
    for k in range(min(6, len(lines))):
        if lines[k].startswith("updated:"):
            lines[k] = f"updated: {today}"
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.replace(tmp, path)
    return {"ok": True, "line": line, "text": lines[line]}


def schedule(days_ahead=60):
    """日付つき行と繰り返し行を、今日から days_ahead 日ぶん展開して返す"""
    lines, off = _strip_fm(_read("schedule.md"))
    today = datetime.datetime.now(LOCAL).date()
    items = []
    for l in lines:
        m = re.match(r"^\s*-\s+(\d{4}-\d{2}-\d{2})\s*(\d{1,2}:\d{2})?\s*([A-Z]{2,4})?\s*(.*)", l)
        if m:
            try:
                d = datetime.date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if d >= today:
                items.append({"date": d.isoformat(), "time": (m.group(2) or "") + (" " + m.group(3) if m.group(3) else ""),
                              "text": m.group(4).strip(), "repeat": False})
            continue
        m = re.match(r"^\s*-\s+毎日\s*(\d{1,2}:\d{2})?\s*([A-Z]{2,4})?\s*(.*)", l)
        mw = re.match(r"^\s*-\s+毎週\s*([月火水木金土日]+)\s*(\d{1,2}:\d{2})?\s*([A-Z]{2,4})?\s*(.*)", l)
        # 「第」の繰り返しも読む(2026-09-23)。文字クラスに「第」が無かったため
        # `毎月 第2・第4 月曜` が読めず(`第2・` で止まる)、note 記事公開の予定が
        # /plan にも朝の便りにも**一度も出ていなかった**。`第2・4` の書き方は元から通る。
        mm = re.match(r"^\s*-\s+毎月\s*(第[\d・,、第]+\s*[月火水木金土日])曜?\s*(\d{1,2}:\d{2})?\s*([A-Z]{2,4})?\s*(.*)", l)
        if not (m or mw or mm):
            continue
        if m:
            kind, spec, tm, tz, text = "daily", "", m.group(1), m.group(2), m.group(3)
        elif mw:
            kind, spec, tm, tz, text = "weekly", mw.group(1), mw.group(2), mw.group(3), mw.group(4)
        else:
            kind, spec, tm, tz, text = "monthly", mm.group(1), mm.group(2), mm.group(3), mm.group(4)
        time_s = (tm or "") + (" " + tz if tz else "")
        for n in range(days_ahead):
            d = today + datetime.timedelta(days=n)
            if kind == "daily":
                hit = True
            elif kind == "weekly":
                hit = WD[d.weekday()] in spec
            else:
                nths = re.findall(r"\d", spec)
                wd = spec[-1]
                hit = str((d.day - 1) // 7 + 1) in nths and WD[d.weekday()] == wd
            if hit:
                items.append({"date": d.isoformat(), "time": time_s, "text": text.strip(), "repeat": kind})
    items.sort(key=lambda x: (x["date"], x["time"]))
    return items


def today_events():
    """今日の予定だけ(毎日の繰り返しは除く)。朝の便り用"""
    today = datetime.datetime.now(LOCAL).date().isoformat()
    return [e for e in schedule(1) if e["date"] == today and e["repeat"] != "daily"]


def plan():
    today = datetime.datetime.now(LOCAL).date()
    ts = tasks()
    for t in ts:
        if t["due"] and not t["done"]:
            try:
                t["overdue"] = datetime.date.fromisoformat(t["due"]) < today
            except ValueError:
                t["overdue"] = False
    return {"today": today.isoformat(), "weekday": WD[today.weekday()], "goals": goals(), "tasks": ts, "schedule": schedule(),
            "updated": {n: os.path.getmtime(os.path.join(PLAN_DIR, n)) if os.path.exists(os.path.join(PLAN_DIR, n)) else 0
                        for n in ("goals.md", "tasks.md", "schedule.md")}}


if __name__ == "__main__":
    import json
    print(json.dumps(plan(), ensure_ascii=False, indent=1)[:3000])
