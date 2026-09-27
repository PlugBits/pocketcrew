#!/usr/bin/env python3
"""~/vault/workout/log.md の解析 + Strong 系アプリの CSV 取り込み。
CLI:
  python3 workout.py import <csv path>       1ファイル取り込み
  python3 workout.py import-inbox            inbox/*.csv を全部取り込み(取り込んだ CSV は inbox/imported/ へ)
  どちらも --dry-run で、書き込まずに差分(追加/置換する節の見出し)を表示するだけ。
API 用途: parse_log() が log.md を構造化して返す(server.py から import)。
"""
import os, re, csv, sys, glob, shutil, datetime, collections

_ROOT = os.path.dirname(os.path.realpath(__file__))   # realpath: symlink 経由でも根を見つける
while not os.path.isdir(os.path.join(_ROOT, "core")):
    _ROOT = os.path.dirname(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from core import config as C
from core import collect

LOG_PATH = C.vault_path("workout_log")
INBOX = C.INBOX
IMPORTED_DIR = os.path.join(INBOX, "imported")
WD = "月火水木金土日"
LOCAL = datetime.datetime.now().astimezone().tzinfo
LB_PER_KG = 2.20462
KG_PER_LB = 0.45359

SECTION_RE = re.compile(r"^##\s+(\d{4}-\d{2}-\d{2})\s+([月火水木金土日])\s+(.*)$")
EX_RE = re.compile(r"^-\s*(.+?)\s*\|\s*\d+\s*セット\s*\|\s*[\d.]+\s*lb\s*×\s*[\d.]+(?:\s*\|\s*sets:\s*(.*))?\s*$")
SET_RE = re.compile(r"([\d.]+)\s*×\s*([\d.]+)")

# 部位分類(簡易・先に当たったものを優先)
PART_RULES = [
    (re.compile(r"face pull", re.I), "Shoulders"),
    (re.compile(r"leg|calf|squat", re.I), "Legs"),
    (re.compile(r"lat|row|pull", re.I), "Back"),
    (re.compile(r"curl", re.I), "Arms"),
    (re.compile(r"press", re.I), "Chest/Shoulders"),
]

# Strong CSV 列名の候補(英語版 / 日本語版)
COLUMN_CANDIDATES = {
    "date": ["Date", "日付"],
    "workout": ["Workout Name", "ワークアウト名"],
    "duration": ["Duration", "時間"],
    "exercise": ["Exercise Name", "エクササイズ名", "種目"],
    "set_order": ["Set Order", "セット順"],
    "weight": ["Weight", "重量"],
    "weight_unit": ["Weight Unit", "重量の単位", "単位"],
    "reps": ["Reps", "レップス", "回数"],
    "distance": ["Distance", "距離"],
    "seconds": ["Seconds", "秒"],
    "notes": ["Notes", "ノート"],
    "workout_notes": ["Workout Notes", "ワークアウトノート"],
    "rpe": ["RPE"],
}
REQUIRED_COLS = ("date", "workout", "exercise", "set_order", "weight", "reps")


def _num(x):
    """40.0 -> '40', 17.5 -> '17.5' のように無駄な小数を削る"""
    f = float(x)
    if f.is_integer():
        return str(int(f))
    return ("%g" % f)


def _part(name):
    for rx, part in PART_RULES:
        if rx.search(name):
            return part
    return "Other"


def _workout_part(name, exercises):
    low = name.lower()
    if "leg" in low:
        return "Legs"
    if "push" in low:
        return "Chest/Shoulders"
    if "pull" in low:
        return "Back"
    if "arm" in low:
        return "Arms"
    counts = collections.Counter(_part(e["name"]) for e in exercises)
    if not counts:
        return "Other"
    # Other 以外があればそちらを優先
    best = [p for p in counts if p != "Other"]
    if best:
        return max(best, key=lambda p: counts[p])
    return "Other"


# ---------------- log.md 解析 ----------------

def _read_lines():
    if not os.path.exists(LOG_PATH):
        return []
    with open(LOG_PATH, encoding="utf-8") as f:
        return f.read().split("\n")


def _frontmatter(lines):
    unit = "lb"
    end = 0
    if lines and lines[0].strip() == "---":
        try:
            j = lines.index("---", 1)
            for l in lines[1:j]:
                m = re.match(r"unit:\s*(\S+)", l)
                if m:
                    unit = m.group(1)
            end = j + 1
        except ValueError:
            pass
    return unit, end


def _body_start(lines):
    """最初の '## ' 行の index(見出し前がヘッダ/書式説明)"""
    for i, l in enumerate(lines):
        if l.startswith("## "):
            return i
    return len(lines)


def _parse_sections(lines):
    """見出し以降を種目・セットまで構造化する(total_lb/pr は計算前の生データ)。
    戻り値: [{date, weekday, name, duration_min, exercises:[{name, sets:[{lb,reps}]}]}]"""
    out, cur = [], None
    for l in lines:
        m = SECTION_RE.match(l)
        if m:
            cur = {"date": m.group(1), "weekday": m.group(2), "name": m.group(3).strip(),
                   "duration_min": None, "exercises": []}
            out.append(cur)
            continue
        if cur is None:
            continue
        m = re.search(r"時間:\s*(\d+)\s*分", l)
        if m and "セット" not in l:
            cur["duration_min"] = int(m.group(1))
            continue
        m = EX_RE.match(l)
        if m:
            name = m.group(1).strip()
            sets = []
            if m.group(2):
                for wm in SET_RE.finditer(m.group(2)):
                    sets.append({"lb": float(wm.group(1)), "reps": float(wm.group(2))})
            if not sets:
                # sets: が無い旧形式 → 3列目の「ベスト重量 × 回数」から 1 セットだけ復元
                bm = re.search(r"\|\s*([\d.]+)\s*lb\s*×\s*([\d.]+)", l)
                if bm:
                    sets = [{"lb": float(bm.group(1)), "reps": float(bm.group(2))}]
            cur["exercises"].append({"name": name, "sets": sets})
    return out


def _compute_totals_pr(workouts):
    """workouts を日付昇順で受け取り、total_lb/pr/best/volume_lb を計算して各要素に埋める。
    戻り値: prs のリスト(日付昇順)"""
    hist_best = {}
    prs = []
    for w in sorted(workouts, key=lambda x: x["date"]):
        total = 0.0
        pr = 0
        for e in w["exercises"]:
            sets = e["sets"]
            vol = sum(s["lb"] * s["reps"] for s in sets)
            e["volume_lb"] = round(vol, 1)
            best = max(sets, key=lambda s: (s["lb"], s["reps"])) if sets else {"lb": 0, "reps": 0}
            e["best"] = {"lb": best["lb"], "reps": best["reps"]}
            total += vol
            prev = hist_best.get(e["name"])
            if prev is not None and best["lb"] > prev:
                pr += 1
                prs.append({"date": w["date"], "exercise": e["name"], "lb": best["lb"], "reps": best["reps"], "prev_lb": prev})
            hist_best[e["name"]] = max(prev or 0, best["lb"])
        w["total_lb"] = round(total, 1)
        w["pr"] = pr
    return prs


def _e1rm(lb, reps):
    """推定 1RM(Epley)。重量 0(自重)は 0。回数 1 はそのまま重量を返す。小数 1 桁。"""
    lb = float(lb or 0)
    reps = float(reps or 0)
    if lb <= 0:
        return 0.0
    if reps <= 1:
        return round(lb, 1)
    return round(lb * (1 + reps / 30), 1)


def _monday(d):
    return d - datetime.timedelta(days=d.weekday())


def _improved(workouts):
    """種目ごとに(日付昇順の)最初と最新の e1rm を比べる。対象は記録が 2 日以上あり、
    最初・最新とも e1rm > 0(自重のみの種目は除外)の種目。"""
    by_ex = collections.OrderedDict()
    for w in sorted(workouts, key=lambda x: x["date"]):
        for e in w["exercises"]:
            best = e.get("best") or {}
            e1rm = _e1rm(best.get("lb", 0), best.get("reps", 0))
            by_ex.setdefault(e["name"], []).append({"date": w["date"], "lb": best.get("lb", 0), "e1rm": e1rm})
    up, items = 0, []
    for name, pts in by_ex.items():
        if len(pts) < 2:
            continue
        first, last = pts[0], pts[-1]
        if first["e1rm"] <= 0 or last["e1rm"] <= 0:
            continue
        is_up = last["e1rm"] > first["e1rm"]
        if is_up:
            up += 1
        items.append({"name": name, "first_lb": first["lb"], "latest_lb": last["lb"],
                       "first_e1rm": first["e1rm"], "latest_e1rm": last["e1rm"]})
    return {"up": up, "total": len(items), "items": items}


def _kpi(workouts):
    now = datetime.datetime.now(LOCAL).date()
    this_monday = _monday(now)
    counts = collections.Counter(_monday(datetime.date.fromisoformat(w["date"])) for w in workouts)
    starts = [this_monday - datetime.timedelta(weeks=i) for i in range(7, -1, -1)]
    weeks = [{"start": s.isoformat(), "count": counts.get(s, 0)} for s in starts]
    this_week = counts.get(this_monday, 0)
    streak = 0
    wk = this_monday if this_week > 0 else this_monday - datetime.timedelta(weeks=1)
    while counts.get(wk, 0) >= 1:
        streak += 1
        wk -= datetime.timedelta(weeks=1)
    return {"weeks": weeks, "this_week": this_week, "streak_weeks": streak, "improved": _improved(workouts)}


def _freq(workouts):
    now = datetime.datetime.now(LOCAL).date()
    this_month = now.strftime("%Y-%m")
    last_month = (now.replace(day=1) - datetime.timedelta(days=1)).strftime("%Y-%m")

    def bucket(month):
        by_name, by_part = collections.OrderedDict(), collections.OrderedDict()
        for w in workouts:
            if w["date"][:7] != month:
                continue
            by_name[w["name"]] = by_name.get(w["name"], 0) + 1
            part = _workout_part(w["name"], w["exercises"])
            by_part[part] = by_part.get(part, 0) + 1
        return {"month": month, "by_name": dict(by_name), "by_part": dict(by_part)}

    return {"this_month": bucket(this_month), "last_month": bucket(last_month)}


def parse_log():
    lines = _read_lines()
    unit, _ = _frontmatter(lines)
    workouts = _parse_sections(lines)
    prs = _compute_totals_pr(workouts)
    workouts_desc = sorted(workouts, key=lambda w: w["date"], reverse=True)
    exmap = collections.OrderedDict()
    for w in sorted(workouts, key=lambda x: x["date"]):
        for e in w["exercises"]:
            exmap.setdefault(e["name"], []).append({"date": w["date"], "best_lb": e["best"]["lb"],
                                                      "best_reps": e["best"]["reps"], "volume_lb": e["volume_lb"],
                                                      "e1rm": _e1rm(e["best"]["lb"], e["best"]["reps"])})
    return {
        "unit": unit,
        "workouts": [{k: v for k, v in w.items()} for w in workouts_desc],
        "exercises": exmap,
        "prs": sorted(prs, key=lambda p: p["date"], reverse=True),
        "freq": _freq(workouts),
        "kpi": _kpi(workouts),
        "inbox_csv": len(glob.glob(os.path.join(INBOX, "*.csv"))),
    }


# ---------------- CSV 取り込み ----------------

def _resolve_columns(fieldnames):
    fieldnames = fieldnames or []
    resolved, warnings = {}, []
    for key, cands in COLUMN_CANDIDATES.items():
        found = next((c for c in cands if c in fieldnames), None)
        resolved[key] = found
        if not found and key in REQUIRED_COLS:
            warnings.append(f"列が見つかりません: {key}(候補 {cands})")
    return resolved, warnings


def _is_int_str(s):
    return bool(re.fullmatch(r"\d+", (s or "").strip()))


def _parse_duration(raw):
    m = re.search(r"(\d+)", raw or "")
    return int(m.group(1)) if m else None


def read_csv_workouts(path):
    """CSV を読んで [{date,name,duration_min,exercises:[{name,sets:[{lb,reps}]}]}] と warnings を返す。
    セット順が数字でない行(休憩タイマー等)は除外する。"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        cols, warnings = _resolve_columns(reader.fieldnames)
    if any(cols[k] is None for k in REQUIRED_COLS):
        return [], warnings  # 必須列が無ければ諦める

    def g(row, key):
        c = cols[key]
        return (row.get(c) or "").strip() if c else ""

    groups = collections.OrderedDict()
    skipped_rest = 0
    for row in rows:
        so = g(row, "set_order")
        if not _is_int_str(so):
            skipped_rest += 1
            continue
        date_full = g(row, "date")
        date = date_full[:10]
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            warnings.append(f"日付を解釈できない行をスキップ: {date_full!r}")
            continue
        name = g(row, "workout") or "(無題)"
        key = (date, name)
        w = groups.setdefault(key, {"date": date, "name": name, "duration_min": _parse_duration(g(row, "duration")),
                                     "exercises": collections.OrderedDict()})
        exname = g(row, "exercise") or "(不明)"
        weight_s, reps_s = g(row, "weight"), g(row, "reps")
        try:
            weight = float(weight_s) if weight_s else 0.0
        except ValueError:
            weight = 0.0
        try:
            reps = float(reps_s) if reps_s else 0.0
        except ValueError:
            reps = 0.0
        unit = g(row, "weight_unit").lower()
        if unit == "kg":
            weight = round(weight * LB_PER_KG, 1)
        elif unit and unit not in ("lb", "lbs"):
            warnings.append(f"未知の重量単位 {unit!r} をそのまま lb として扱います")
        w["exercises"].setdefault(exname, []).append({"lb": weight, "reps": reps, "so": int(so)})

    out = []
    for w in groups.values():
        exercises = []
        for exname, sets in w["exercises"].items():
            sets_sorted = sorted(sets, key=lambda s: s["so"])
            exercises.append({"name": exname, "sets": [{"lb": s["lb"], "reps": s["reps"]} for s in sets_sorted]})
        out.append({"date": w["date"], "name": w["name"], "duration_min": w["duration_min"], "exercises": exercises})
    if skipped_rest:
        warnings.append(f"セット順が数字でない行を {skipped_rest} 件除外しました(休憩タイマー等)")
    return out, warnings


def _render_section(w):
    d = datetime.date.fromisoformat(w["date"])
    weekday = WD[d.weekday()]
    lines = [f"## {w['date']} {weekday} {w['name']}"]
    parts = []
    if w.get("duration_min") is not None:
        parts.append(f"時間: {w['duration_min']}分")
    parts.append(f"総重量: {_num(w['total_lb'])} lb")
    parts.append(f"PR: {w['pr']}")
    lines.append("  ".join(parts))
    for e in w["exercises"]:
        sets = e["sets"]
        n = len(sets)
        best = e["best"]
        sets_str = ", ".join(f"{_num(s['lb'])}×{_num(s['reps'])}" for s in sets)
        lines.append(f"- {e['name']} | {n}セット | {_num(best['lb'])} lb × {_num(best['reps'])} | sets: {sets_str}")
    return lines


def _merge_and_render(new_workouts):
    """既存 log.md の節と new_workouts(date+name が同じなら置換)をマージし、
    (最終 lines, 追加された見出し, 置換された見出し) を返す。ファイルへは書き込まない。"""
    lines = _read_lines()
    unit, fm_end = _frontmatter(lines)
    body_start = _body_start(lines)
    header = lines[:body_start]
    existing = _parse_sections(lines[body_start:])
    existing_keys = {(w["date"], w["name"]) for w in existing}
    new_keys = {(w["date"], w["name"]) for w in new_workouts}

    merged = {(w["date"], w["name"]): w for w in existing}
    for w in new_workouts:
        merged[(w["date"], w["name"])] = w
    all_workouts = list(merged.values())
    _compute_totals_pr(all_workouts)
    all_workouts.sort(key=lambda w: w["date"], reverse=True)

    added = sorted(k for k in new_keys - existing_keys)
    replaced = sorted(k for k in new_keys & existing_keys)

    body_lines = []
    for w in all_workouts:
        body_lines += _render_section(w)
        body_lines.append("")
    while body_lines and body_lines[-1] == "":
        body_lines.pop()

    today = datetime.datetime.now(LOCAL).strftime("%Y-%m-%d")
    if fm_end:
        for i in range(fm_end):
            if header[i].startswith("updated:"):
                header[i] = f"updated: {today}"
    return header + body_lines, added, replaced


def import_csv(path, dry_run=False):
    new_workouts, warnings = read_csv_workouts(path)
    for w in warnings:
        print(f"警告: {w}", file=sys.stderr)
    if not new_workouts:
        print("取り込める行がありませんでした。", file=sys.stderr)
        return {"ok": False, "error": "no rows", "warnings": warnings}
    final_lines, added, replaced = _merge_and_render(new_workouts)
    if dry_run:
        print(f"[dry-run] {path}: 追加 {len(added)} 件、置換 {len(replaced)} 件")
        for d, n in added:
            print(f"  + {d} {n}")
        for d, n in replaced:
            print(f"  ~ {d} {n}")
        return {"ok": True, "dry_run": True, "added": added, "replaced": replaced, "workouts": len(new_workouts), "warnings": warnings}
    tmp = LOG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(final_lines) + "\n")
    os.replace(tmp, LOG_PATH)
    return {"ok": True, "added": added, "replaced": replaced, "workouts": len(new_workouts), "warnings": warnings}


def import_inbox(dry_run=False):
    os.makedirs(IMPORTED_DIR, exist_ok=True)
    csvs = sorted(glob.glob(os.path.join(INBOX, "*.csv")))
    results = []
    for path in csvs:
        res = import_csv(path, dry_run=dry_run)
        res["file"] = os.path.basename(path)
        results.append(res)
        if res.get("ok") and not dry_run:
            collect.log_action("workout-import", file=path, workouts=res["workouts"])
            shutil.move(path, os.path.join(IMPORTED_DIR, os.path.basename(path)))
    return {"ok": True, "dry_run": dry_run, "files": len(csvs), "results": results}


if __name__ == "__main__":
    import json
    args = sys.argv[1:]
    dry = "--dry-run" in args
    args = [a for a in args if a != "--dry-run"]
    if args[:1] == ["import"] and len(args) > 1:
        print(json.dumps(import_csv(args[1], dry_run=dry), ensure_ascii=False, indent=1, default=str))
    elif args[:1] == ["import-inbox"]:
        print(json.dumps(import_inbox(dry_run=dry), ensure_ascii=False, indent=1, default=str))
    else:
        print(json.dumps(parse_log(), ensure_ascii=False, indent=1, default=str)[:3000])
