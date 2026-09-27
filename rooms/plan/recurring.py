#!/usr/bin/env python3
"""~/vault/plan/schedule.md の「## 定期」行を、通知に使える短い形にする。

plan.py の schedule() が既に「毎日/毎週/毎月第N」を実際の日付へ展開できるので、
ここではそのパーサを作り直さず、schedule() の出力を再利用するだけにする。

ただし schedule() は「今日から days_ahead 日ぶん」しか先に展開しない(過去へは
遡らない)ため、そのまま日付でフィルタするだけでは「過去の日に何があったか」を
answer できない。曜日(毎週)・第何週×曜日(毎月)という条件自体は d 自身から
計算できる値なので、schedule() の展開結果(既定60日ぶん。毎週なら全曜日、毎月
なら最低1回は含まれる)から行ごとの「どの曜日/第何週×曜日で当たるか」という
パターンを逆算し、それを任意の d に当てはめる。正規表現を複製しない代わりに、
schedule() が実際に生成した日付から規則を読み取る、という形で再利用している。
"""
import os
import re
import sys
import datetime

import plan

LOCAL = plan.LOCAL
WD = plan.WD  # "月火水木金土日"
SCHEDULE_PATH = os.path.join(plan.PLAN_DIR, "schedule.md")

# unreadable_lines() 専用: plan.py の schedule() 内にある4つの正規表現の写し。
# データの取り出しはあくまで plan.schedule() を呼んで行う(下の _patterns() 参照)。
# ここでは「読める形式かどうか」だけを判定するために、同じ形を照合用に持つ。
_DATE_RE = re.compile(r"^\s*-\s+(\d{4}-\d{2}-\d{2})\s*(\d{1,2}:\d{2})?\s*([A-Z]{2,4})?\s*(.*)")
_DAILY_RE = re.compile(r"^\s*-\s+毎日\s*(\d{1,2}:\d{2})?\s*([A-Z]{2,4})?\s*(.*)")
_WEEKLY_RE = re.compile(r"^\s*-\s+毎週\s*([月火水木金土日]+)\s*(\d{1,2}:\d{2})?\s*([A-Z]{2,4})?\s*(.*)")
# 「第」の繰り返しも読む(2026-09-23)。plan.py 側と同じ直しを当てている。
# ここは plan.py の正規表現の写しなので、**片方だけ直すとズレる**。plan.py:毎月 と対で見ること。
_MONTHLY_RE = re.compile(r"^\s*-\s+毎月\s*(第[\d・,、第]+\s*[月火水木金土日])曜?\s*(\d{1,2}:\d{2})?\s*([A-Z]{2,4})?\s*(.*)")
_ITEM_RE = re.compile(r"^\s*-\s+")


def _patterns():
    """plan.schedule() の展開結果(既定60日ぶん)から、繰り返し行ごとの発生条件を逆算する。
    毎週の行 → その行が実際に出現した曜日の集合(=元のスペック「月水金土」など)。
    毎月の行 → (第何週, 曜日) の組の集合。
    daily と日付つき(repeat=False)は対象外(依頼どおり)。"""
    weekly, monthly = {}, {}
    for it in plan.schedule():
        if it["repeat"] not in ("weekly", "monthly"):
            continue
        key = (it["time"], it["text"])
        d = datetime.date.fromisoformat(it["date"])
        wd_char = WD[d.weekday()]
        if it["repeat"] == "weekly":
            weekly.setdefault(key, set()).add(wd_char)
        else:
            nth = str((d.day - 1) // 7 + 1)
            monthly.setdefault(key, set()).add((nth, wd_char))
    return weekly, monthly


def _weekday_segment(text: str, wd_char: str):
    """本文中の「<曜日>=…」を切り出す。誤爆防止のため [月火水木金土日]\\s*= の形だけを見る。
    区切りは " / " "。" ")" に加えて "(" も見る。理由: 実データに
    「金=週末の買い出し前に(判定後は…)」のような入れ子の括弧があり、"(" を区切りに
    入れないと後ろの注記まで巻き込んでしまう(実際にテストして確認した)。"""
    for m in re.finditer(r"([月火水木金土日])\s*=\s*", text):
        if m.group(1) != wd_char:
            continue
        rest = text[m.end():]
        cut = len(rest)
        for sep in (" / ", "。", "(", "(", ")", ")"):
            idx = rest.find(sep)
            if idx != -1:
                cut = min(cut, idx)
        seg = rest[:cut].strip()
        if seg:
            return seg
    return None


def _label(text: str, wd_char: str) -> str:
    """短い名前を作る。Instagram 専用にはしない(定期行すべてに同じ規則を使う)。
    1) 「<その日の曜日>=…」があればそれを切り出す
    2) 無ければ本文の先頭を括弧の手前までで切る
    3) それでも取れなければ先頭40字"""
    seg = _weekday_segment(text, wd_char)
    if seg:
        return seg
    for paren in ("(", "("):
        idx = text.find(paren)
        if idx > 0:
            return text[:idx].strip()
    return text[:40].strip()


def slots_on(d: datetime.date):
    """d(datetime.date)に該当する定期行。戻りは
    [{"time": "12:00 EDT", "text": "<元の全文>", "label": "<短い名前>", "repeat": "weekly"}]
    並びは time の昇順。"""
    weekly, monthly = _patterns()
    wd_char = WD[d.weekday()]
    nth = str((d.day - 1) // 7 + 1)
    out = []
    for (time_s, text), wdset in weekly.items():
        if wd_char in wdset:
            out.append({"time": time_s, "text": text, "label": _label(text, wd_char), "repeat": "weekly"})
    for (time_s, text), pairs in monthly.items():
        if (nth, wd_char) in pairs:
            out.append({"time": time_s, "text": text, "label": _label(text, wd_char), "repeat": "monthly"})
    out.sort(key=lambda x: x["time"])
    return out


def brief_line(d: datetime.date) -> str:
    """朝の便り用の1行。該当が無ければ空文字(無理に埋めない)。
    例: "12:00 EDT カードの使い分け / 09:00 JST X 投稿" """
    slots = slots_on(d)
    if not slots:
        return ""
    return " / ".join(f"{s['time']} {s['label']}".strip() for s in slots)


def tomorrow_notice(d: datetime.date):
    """d の前日の夜に出す予告。d に該当が無ければ None。
    戻りは {"title": "...", "body": "..."}。複数あれば並べる。"""
    slots = slots_on(d)
    if not slots:
        return None
    wd_char = WD[d.weekday()]
    names = "、".join(s["label"] for s in slots)
    return {
        "title": f"明日の予定({d.month}/{d.day} {wd_char})",
        "body": f"明日は{names}。素材はあるか",
    }


def unreadable_lines():
    """「## 定期」の中で、plan.py のパーサ(毎日/毎週/毎月/日付つき)のどれにも
    当たらなかった `- ` 行の一覧。書式が揺れている行を落とさずに気づくためのもの。"""
    try:
        with open(SCHEDULE_PATH, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except OSError:
        return []
    out = []
    in_section = False
    for l in lines:
        if re.match(r"^##\s+定期\s*$", l):
            in_section = True
            continue
        if in_section and re.match(r"^##\s+", l):
            break
        if not in_section:
            continue
        if not _ITEM_RE.match(l):
            continue
        if not (_DATE_RE.match(l) or _DAILY_RE.match(l) or _WEEKLY_RE.match(l) or _MONTHLY_RE.match(l)):
            out.append(l)
    return out


# ---------- 自己テスト(python3 recurring.py --selftest)。他の room の --selftest と同じ作り ----------
class _SelfTest(__import__("unittest").TestCase):
    def test_wednesday_shows_card_switching(self):
        self.assertIn("カードの使い分け", brief_line(datetime.date(2026, 9, 23)))

    def test_ig_label_matches_each_weekday(self):
        self.assertIn("今週の目玉", brief_line(datetime.date(2026, 9, 21)))       # 月
        self.assertIn("週末の買い出し前に", brief_line(datetime.date(2026, 9, 25)))  # 金
        self.assertIn("型5 週末のおでかけ", brief_line(datetime.date(2026, 9, 26)))  # 土

    def test_non_ig_weekdays_have_no_post(self):
        self.assertNotIn("投稿", brief_line(datetime.date(2026, 9, 22)))  # 火
        self.assertNotIn("投稿", brief_line(datetime.date(2026, 9, 24)))  # 木

    def test_daily_is_excluded(self):
        for n in range(14):
            d = datetime.date(2026, 9, 21) + datetime.timedelta(days=n)
            self.assertNotIn("日次まとめ", brief_line(d))

    def test_monthly_matching_logic_second_and_fourth_monday(self):
        # 実物の schedule.md の「第2・第4」(第が2回)は plan.py の毎月パーサに
        # 当たらず読めない(下の test_unreadable_lines_catches_the_real_gap で検出)。
        # 「第何週×曜日」の判定ロジック自体は、読める書式(第2・4)の一時ファイルで確かめる。
        # plan.py は書き換えない・恒久的な差し替えでもない(finally で必ず戻す)。
        import tempfile
        tmp_dir = tempfile.mkdtemp()
        with open(os.path.join(tmp_dir, "schedule.md"), "w", encoding="utf-8") as f:
            f.write("## 定期\n- 毎月 第2・4 月曜 note 記事公開(09:00 JST)\n")
        orig = plan.PLAN_DIR
        plan.PLAN_DIR = tmp_dir
        try:
            self.assertIn("note 記事公開", brief_line(datetime.date(2026, 10, 12)))     # 2026-10の第2月曜
            self.assertIn("note 記事公開", brief_line(datetime.date(2026, 10, 26)))     # 第4月曜
            self.assertNotIn("note 記事公開", brief_line(datetime.date(2026, 10, 5)))   # 第1月曜は対象外
        finally:
            plan.PLAN_DIR = orig

    def test_date_only_line_is_excluded(self):
        # 「## 予定」の日付つき行(repeat=False)は定期行ではないので出ない
        self.assertNotIn("Mac mini", brief_line(datetime.date(2026, 9, 22)))

    def test_tomorrow_notice_shape(self):
        n = tomorrow_notice(datetime.date(2026, 9, 23))
        self.assertIsNotNone(n)
        self.assertIn("title", n)
        self.assertIn("body", n)
        self.assertIsNone(tomorrow_notice(datetime.date(2026, 9, 22)))  # 火曜は該当なし

    def test_unreadable_lines_catches_the_real_gap(self):
        # 実物の schedule.md には「毎月 第2・第4 月曜 note 記事公開」があるが、
        # plan.py の毎月の正規表現は「第」の繰り返しに対応しておらず読めない。
        # これを黙って落とさずに拾えているかを確かめる(unreadable_lines() の本来の目的)。
        got = unreadable_lines()
        self.assertEqual(got, ["- 毎月 第2・第4 月曜 note 記事公開(09:00 JST)"])


def main():
    if "--selftest" in sys.argv:
        import unittest
        sys.argv.remove("--selftest")
        r = unittest.TextTestRunner(verbosity=2).run(
            unittest.TestLoader().loadTestsFromTestCase(_SelfTest))
        return 0 if r.wasSuccessful() else 1
    today = datetime.datetime.now(LOCAL).date()
    print(brief_line(today) or "(該当なし)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
