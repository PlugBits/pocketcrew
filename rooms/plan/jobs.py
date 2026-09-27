"""期限リマインド・前日の枠予告・朝の便りの「plan」分の段。core/server.py の同名関数をそのまま移した。"""
import os
import time
import datetime

from core import config as C
from core import collect
from core import util

import plan
import recurring


def due_reminder(slot: str, force=False):
    """08:00/18:00(ローカル)に1回。未完了で期限が来ているタスクがあればWeb Push 1通。0件なら送らない。
    18:00は「今日まで」だけ(超過分は朝で済んでいる)。二重送信は log/remind-YYYY-MM-DD-{slot}.done で防ぐ。"""
    day = collect.now().strftime("%Y-%m-%d")
    mark = os.path.join(collect.LOG_DIR, f"remind-{day}-{slot}.done")
    if os.path.exists(mark) and not force:
        return {"ok": True, "skipped": "already done"}
    p = plan.plan()
    today = p["today"]
    todo = [t for t in p["tasks"] if not t["done"] and t["due"]]
    targets = [t for t in todo if t["due"] <= today] if slot == "08" else [t for t in todo if t["due"] == today]
    os.makedirs(collect.LOG_DIR, exist_ok=True)
    with open(mark, "w", encoding="utf-8") as f:
        f.write(collect.now().isoformat(timespec="seconds"))
    if not targets:
        return {"ok": True, "sent": False, "count": 0}
    title = f"期限のタスク {len(targets)}件"
    body = "・".join(t["text"] for t in targets[:3])
    push_res = util.notify(title, body, "/plan", f"remind-{slot}")
    collect.log_action("remind", slot=slot, count=len(targets))
    return {"ok": True, "sent": True, "count": len(targets), "title": title, "body": body, "push": push_res}


def slot_notice_check(force=False):
    """毎分呼ばれ、ローカル20:00(C.SLOT_NOTICE_HOUR/MIN)以降でまだの日なら1回だけ:
    明日の schedule.md ## 定期の枠を recurring.tomorrow_notice() で調べ、該当があれば前日予告のWeb Push。
    該当なしなら送らない(無理に埋めない)。二重実行は log/slot-notice-YYYY-MM-DD.done で防ぐ
    (他 room の定時ジョブと同じ、時刻を過ぎていて未実行なら1回・追いつき方式)。"""
    now = time.localtime()
    if not (now.tm_hour > C.SLOT_NOTICE_HOUR or (now.tm_hour == C.SLOT_NOTICE_HOUR and now.tm_min >= C.SLOT_NOTICE_MIN)):
        return {"ok": True, "skipped": "not due"}
    day = collect.now().strftime("%Y-%m-%d")
    mark = os.path.join(collect.LOG_DIR, f"slot-notice-{day}.done")
    if os.path.exists(mark) and not force:
        return {"ok": True, "skipped": "already done"}
    os.makedirs(collect.LOG_DIR, exist_ok=True)
    with open(mark, "w", encoding="utf-8") as f:
        f.write(collect.now().isoformat(timespec="seconds"))
    at = "%02d:%02d" % (C.SLOT_NOTICE_HOUR, C.SLOT_NOTICE_MIN)
    tomorrow = collect.now().date() + datetime.timedelta(days=1)
    notice = recurring.tomorrow_notice(tomorrow)
    if not notice:
        collect.log_action("slot-notice", sent=False, day=day, at=at)
        return {"ok": True, "sent": False, "at": at}
    title = str(notice.get("title") or "明日の枠")
    body = str(notice.get("body") or "")
    push_res = util.notify(title, body, "/plan", f"slot-notice-{day}")
    collect.log_action("slot-notice", sent=True, day=day, at=at, title=title, body=body)
    return {"ok": True, "sent": True, "at": at, "title": title, "body": body, "push": push_res}


def BRIEF(day):
    """朝の便りの「plan」分の段(daily 側が全 room の段を集めて組み立てる)。
    morning_brief() のうち、今日の枠・今日の予定・タスク・読めなかった定期行の部分と同じ内容を返す。"""
    sections = []
    slot = recurring.brief_line(datetime.date.fromisoformat(day))
    if slot:
        sections.append({"order": 0, "lines": ["## 今日の枠", f"- {slot}"], "push": slot})

    events = plan.today_events()
    ev_lines = [f"- {(e['time'] + ' ') if e['time'] else ''}{e['text']}" for e in events] if events else ["- なし"]
    sections.append({"order": 10, "lines": ["## 今日の予定"] + ev_lines})

    p = plan.plan()
    todo = [t for t in p["tasks"] if not t["done"]]
    over = [t for t in todo if t.get("overdue")]
    due_today = [t for t in todo if t["due"] and not t.get("overdue") and t["due"] <= p["today"]]
    lines = ["## タスク", f"- 期限超過: {len(over)}件"]
    lines += [f"  - {t['text']}" for t in over[:2]]
    lines.append(f"- 今日まで: {len(due_today)}件")
    lines += [f"  - {t['text']}" for t in due_today[:2]]
    lines.append(f"- 未完了合計: {len(todo)}件")
    sections.append({"order": 11, "lines": lines,
                      "push": f"予定 {len(events)}件 · 期限超過 {len(over)} · 今日まで {len(due_today)}"})

    unreadable = recurring.unreadable_lines()
    if unreadable:
        collect.log_action("schedule-unreadable", lines=unreadable)
        sections.append({"order": 91, "lines": [f"- 読めなかった定期行: {len(unreadable)}件"], "join": True})

    return sections


JOBS = [
    {"name": f"remind-{h:02d}", "at": f"{h:02d}:00", "fn": (lambda h=h: due_reminder(f"{h:02d}"))}
    for h in C.REMIND_HOURS
] + [
    {"name": "slot-notice", "every": "minute", "fn": slot_notice_check},
]
