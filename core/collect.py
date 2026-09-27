#!/usr/bin/env python3
"""Tiny の生存指標と Claude セッションの状態を集める(標準ライブラリのみ)。
読むのは /proc・tmux・ps・tailscale だけ。会話ログ(~/.claude/projects)や設定ファイルは読まない。"""
import os, sys, fcntl, re, time, json, shutil, subprocess, datetime, threading

# core/collect.py 単体で(root の import collect 経由でなく)直接読み込まれても
# "core" パッケージが見えるように、リポジトリ直下(このファイルの2つ上)を sys.path に足す
_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
from core import config as C

LOCAL = datetime.datetime.now().astimezone().tzinfo  # マシンのローカル時刻(EDT)

def now():
    """マシンのローカルタイムゾーン付きの現在時刻。"""
    return datetime.datetime.now().astimezone()

TMUX_SESSION = C.TMUX_SESSION
CARD_LINES = 12      # カードに出す末尾行数
FULL_LINES = 200     # 展開時の行数

# 別ソケットの tmux サーバーに向けるための下ごしらえ(2026-09-27)。本番は空文字のままで、
# 通常の /tmp/tmux-<uid>/default を見る(挙動は変わらない)。検証用に隔離したサーバーを
# 使うときだけ config.toml の [tmux] socket に名前を書く。全ての tmux 呼び出しはここを
# 経由すること(直接 "tmux" を subprocess/sh に渡さない)。
_TMUX_L = ["-L", C.TMUX_SOCKET] if C.TMUX_SOCKET else []
_TMUX_L_STR = f"-L {C.TMUX_SOCKET} " if C.TMUX_SOCKET else ""


def sh(cmd, timeout=5):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def tmux(*args, **kw):
    """subprocess.run(["tmux", ...]) をソケット指定つきで呼ぶ薄いラッパー(timeout 未指定なら5秒)"""
    kw.setdefault("timeout", 5)
    return subprocess.run(["tmux", *_TMUX_L, *args], **kw)


def shtmux(argstr: str, timeout=5):
    """shtmux(f"...") をソケット指定つきで呼ぶ(パイプ・引用符が要る呼び出し向け)"""
    return sh(f"tmux {_TMUX_L_STR}{argstr}", timeout=timeout)


# ---------- マシン ----------
def cpu_sample():
    with open("/proc/stat") as f:
        p = list(map(int, f.readline().split()[1:]))
    return sum(p), p[3] + p[4]


_cpu_prev = None   # (total, idle) の前回サンプル。初回は差分が取れないので 0.0 を返す


def cpu_percent():
    global _cpu_prev
    t2, i2 = cpu_sample()
    prev, _cpu_prev = _cpu_prev, (t2, i2)
    if prev is None:
        return 0.0
    t1, i1 = prev
    dt = t2 - t1
    return round(100 * (1 - (i2 - i1) / dt), 1) if dt else 0.0


def meminfo():
    m = {}
    with open("/proc/meminfo") as f:
        for line in f:
            k, v = line.split(":")
            m[k] = int(v.split()[0]) * 1024
    return m["MemTotal"], m["MemTotal"] - m["MemAvailable"]


_peers_cache = {"t": 0, "v": []}


def tailscale_peers():
    if time.time() - _peers_cache["t"] < 30:
        return _peers_cache["v"]
    try:
        d = json.loads(sh("tailscale status --json"))
        v = [{"name": p.get("HostName", "?"), "online": bool(p.get("Online"))}
             for p in d.get("Peer", {}).values()]
    except Exception:
        v = []
    _peers_cache["v"] = v
    _peers_cache["t"] = time.time()
    return v


# ---------- セッション状態 ----------
# 画面末尾の文字列から状態を決める。上から順に評価し、最初に当たったもの
STATE_RULES = [
    # ログイン切れ(2026-09-20: 約4週間でリフレッシュトークンが切れ、全スレが一斉に止まって
    # iPhone の Claude アプリから消えた)。本体で claude → /login のあと、カードの再起動で復帰
    ("login",    re.compile(r"Login expired · Please run /login|Not logged in · Run /login")),
    ("trust",    re.compile(r"Is this a project you created or one you trust|Quick safety check", re.I)),
    ("approval", re.compile(r"Do you want to (proceed|make this edit|run|allow|create|delete)|\(y/n\)|Yes, and don't ask again|Yes, allow", re.I)),
    ("choice",   re.compile(r"Enter to confirm · Esc to cancel|❯ 1\. |How is Claude doing this session")),
    ("working",  re.compile(r"esc to interrupt")),
]
PROMPT_EMPTY = re.compile(r"^❯\s*$", re.M)
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
GHOST = re.compile(r"^(?:\x1b\[[0-9;]*m)*❯\s*(?:\x1b\[[0-9;]*m)*\x1b\[2m", re.M)   # ❯ の直後が薄字(SGR 2)
SEPARATOR = re.compile(r"^─{20,}\s*$", re.M)
FOOTER = re.compile(r"^\s*(⏵⏵|⏸|\?\s*for shortcuts|auto mode|accept edits|plan mode|bypass permissions)", re.I)
# カードやまとめに出しても意味のない行(ヒント・更新通知・スピナー・キー案内)
NOISE = re.compile(r"(Tip:|Update installed|Restart to apply|ctrl\+b|esc to interrupt|to run in background|^\s*[^\w\s\-]\s\S+(…\s*\(|\sfor\s\d)|^\s*current work\s*$|^\s*⎿\s*Tip|/btw|shift\+tab|← for agents)", re.I)


def detect_state(tail: str, has_proc: bool):
    if not has_proc:
        return "dead", ""
    # 末尾側だけを見る(古い承認文で誤判定しないよう最後の区切り線以降を優先)
    parts = SEPARATOR.split(tail)
    recent = "\n".join(parts[-3:]) if len(parts) >= 3 else tail
    for name, rx in STATE_RULES:
        m = rx.search(recent)
        if m:
            if name == "working":
                return name, ""
            # ダイアログ本文: 最後の区切り線より後ろで、プロンプト・フッター以外(最大10行)
            block = parts[-2] if len(parts) >= 2 and rx.search(parts[-2]) else recent
            lines = [l.rstrip() for l in block.splitlines()
                     if l.strip() and not FOOTER.match(l) and not l.lstrip().startswith("❯ ") or rx.search(l)]
            lines = [l for l in lines if not re.match(r"^❯\s*$", l.strip())]
            return name, "\n".join(lines[-40:])
    # 入力欄は「最後から2番目の区切り線ブロック」(区切り線 / ❯ 入力欄 / 区切り線 / フッター)。
    # 会話履歴にもユーザー発言が "❯ ..." で残るので、そこを見ると誤判定する
    box = parts[-2] if len(parts) >= 3 else recent
    if PROMPT_EMPTY.search(box):
        return "idle", ""
    if re.search(r"^❯\s+\S", box, re.M):
        return "typed", ""      # 入力欄に未送信の文字がある
    return "unknown", ""


# ---------- AskUserQuestion: 複数質問(タブ形式)の画面を読む(2026-09-27) ----------
# Claude Code の AskUserQuestion は、質問が2つ以上だと画面上部にタブ行が出る
#   例: "←  ☐ Cuisine  ☐ Format  ☐ Budget  ✔ Submit  →"
# 1問だけなら、タブ行はチェック無しの1行だけで "✔ Submit" は出ない(例: " ☐ Coffee")。
# 全問に答えると「Review your answers」の確認画面(タブは Submit が選択状態)に進む。
# どちらの画面でも、選択肢は "❯ 1. " のように現在位置が出るだけで、数字キーを1つ押すと
# 「その場で決定して次のタブへ自動で進む」(Enter は要らない)。
#
# 実機で確認した事故(2026-09-27): 電話側はこれまで choice 状態を「質問文をそのまま見せて、
# 入力欄に数字を打って送ってね」という案内にしていた。その送信経路 send() は数字のあとに
# 必ず Enter を追加送信し、届いたか怪しいと Enter を何度も送り直す(_confirm_delivered)。
# ところがこの送り直しは「入力欄が空になったか」を input_box_draft() で見ており、この関数は
# 選択中の行 "❯ 1. Dine in" を「未送信の下書き」と誤認する。そのため送り直しの Enter が、
# 数字キーで既に進んだ次の質問の先頭候補(推奨)を黙って確定させ、最後は確認画面の
# "1. Submit answers" まで押し進めてしまっていた。答えていない質問が本人の見ないまま
# 提出される、というのがこのバグの実体。
# 対策: choice の回答は send() を経由させず、数字キー1つだけを送る answer_choice() を使う
# (Enter も送り直しも無い)。

TAB_TOKEN_RE = re.compile(r"^([☐☒])\s*(.+)$")
OPTION_RE = re.compile(r"^\s*(❯\s*)?(\d+)\.\s*(.*)$")
CUR_TAB_ANSI_RE = re.compile(r"\x1b\[48;5;\d+m(.*?)\x1b\[49m", re.S)
REVIEW_RE = re.compile(r"Review your answers|Ready to submit your answers")
REVIEW_ITEM_RE = re.compile(r"^\s*[●○]\s*(.*)$")
REVIEW_ANSWER_RE = re.compile(r"^\s*→\s*(.*)$")
CHOICE_RX = dict(STATE_RULES)["choice"]


def _choice_block(tail: str):
    """detect_state と同じ切り出し(最後から2番目の区切り線ブロック)。choice 専用の追加解析に使う"""
    parts = SEPARATOR.split(tail)
    recent = "\n".join(parts[-3:]) if len(parts) >= 3 else tail
    return parts[-2] if len(parts) >= 2 and CHOICE_RX.search(parts[-2]) else recent


def _tabbar_line(block: str):
    """タブ行(☐/☒ を含む行)を返す。無ければ None(承認・信頼・ログイン等、質問ピッカー以外)"""
    for line in block.splitlines():
        if "☐" in line or "☒" in line:
            return line
    return None


def _parse_tabs(line: str):
    """タブ行から [{"title","answered"}] を返す(← / → / ✔ Submit は除く)"""
    tabs = []
    for tok in re.split(r"\s{2,}", line.strip()):
        tok = tok.strip()
        if tok in ("←", "→", "") or tok.startswith("✔"):
            continue
        m = TAB_TOKEN_RE.match(tok)
        if m:
            tabs.append({"title": m.group(2).strip(), "answered": m.group(1) == "☒"})
    return tabs


def _parse_options(lines):
    """選択肢の行を拾う([番号]. ラベル + 次行のインデント説明)。"Type something." は自由入力欄なので除く"""
    out = []
    i = 0
    while i < len(lines):
        m = OPTION_RE.match(lines[i])
        if m:
            label = m.group(3).strip()
            desc = ""
            if i + 1 < len(lines) and not OPTION_RE.match(lines[i + 1]) and lines[i + 1].strip():
                desc = lines[i + 1].strip()
                i += 1
            if label.rstrip(".").strip().lower() not in ("type something", ""):
                out.append({"n": int(m.group(2)), "label": label, "desc": desc, "recommended": bool(m.group(1))})
        i += 1
    return out


def _find_prompt(lines):
    """タブ行・選択肢以外で最初に出てくる行(質問文の本体)"""
    for l in lines:
        s = l.strip()
        if s and not OPTION_RE.match(l) and "☐" not in s and "☒" not in s:
            return s
    return ""


def parse_choice(tail: str, raw: str):
    """choice 状態の画面を構造化する。判定できなければ None(承認・信頼・ログイン・アンケート等)。
    tail は色無しの末尾、raw は色付きの末尾(現在のタブを ANSI の背景色から見分けるのに使う)。"""
    block = _choice_block(tail)
    tabbar = _tabbar_line(block)
    if tabbar is None:
        return None
    lines = [l for l in block.splitlines() if l.strip()]
    is_multi = "✔" in tabbar and "Submit" in tabbar
    if not is_multi:
        # タブ行はあるが Submit が無い = 質問1つだけの画面。電話側は今まで通りの表示に任せる
        return {"kind": "single", "prompt": _find_prompt(lines), "options": _parse_options(lines)}
    tabs = _parse_tabs(tabbar)
    if REVIEW_RE.search(block):
        review = []
        rl = block.splitlines()
        for i, l in enumerate(rl):
            qm = REVIEW_ITEM_RE.match(l)
            if qm and i + 1 < len(rl):
                am = REVIEW_ANSWER_RE.match(rl[i + 1])
                if am:
                    review.append({"q": qm.group(1).strip(), "a": am.group(1).strip()})
        return {"kind": "review", "tabs": tabs, "total": len(tabs), "review": review,
                "options": _parse_options(lines)}
    # 現在のタブ: 色付きの末尾から、背景色つきの区間(選ばれているタブ)のテキストを探す。
    # 一番あとに出てきたもの(=画面の一番下、いちばん新しい描画)を採用する
    cur_title = None
    for m in CUR_TAB_ANSI_RE.finditer(raw):
        t = ANSI.sub("", m.group(1)).strip()
        t = re.sub(r"^[☐☒✔]\s*", "", t).strip()
        if t:
            cur_title = t
    index = next((i + 1 for i, t in enumerate(tabs) if t["title"] == cur_title), None)
    if index is None:
        # 色つき判定に失敗したときの保険: 最初の未回答タブを「いま」とみなす
        index = next((i + 1 for i, t in enumerate(tabs) if not t["answered"]), len(tabs))
    return {"kind": "multi", "tabs": tabs, "total": len(tabs), "index": index,
            "prompt": _find_prompt(lines), "options": _parse_options(lines)}


# 2026-09-22 に「● = 実行中 / ◯ = 終了済み」として ◯ を捨てたが、2026-09-24 の実画面では
# ● は選択中の行(ふだんは main)の印で、実行中のサブエージェントも ◯ だった。そのため衛星が
# 出ず、rc も待機に見えていた。今の Claude Code は終わったサブエージェントを一覧から消すので、
# 印は見ずに main 以外を全部数える。終わった行が残る版に戻ったら、ここを見直すこと。
AGENT_LINE = re.compile(r"^\s*([●◯○])\s+(\S+)(?:\s{2,}(.*?))?\s*$")


def detect_agents(tail: str):
    """フッター(⏵⏵ … ← for agents)より下に並ぶサブエージェントの一覧を返す"""
    lines = tail.splitlines()
    idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if FOOTER.match(lines[i]):
            idx = i
            break
    if idx < 0:
        return []
    out = []
    for l in lines[idx + 1:]:
        m = AGENT_LINE.match(l)
        if not m:
            if l.strip():
                break
            continue
        kind = m.group(2)
        if kind == "main":
            continue
        # 2026-09-24: 印(● / ◯)は「いま選んで見ている行」の印で、実行中かどうかではない
        # (実行中のサブエージェントが ◯ で出ていた)。終わったものは一覧から消えるので、印は見ない。
        rest = (m.group(3) or "").strip()
        # 末尾の「27s · ↓ 23.7k」を分離
        mt = re.search(r"\s{2,}(\d+(?:[smh]|m \d+s)\b.*)$", rest)
        elapsed = mt.group(1).strip() if mt else ""
        desc = rest[:mt.start()].strip() if mt else rest
        out.append({"kind": kind, "desc": desc[:60], "elapsed": elapsed})
    return out


def last_output(tail: str, n: int):
    """フッターやダイアログの飾りを除いた、直近の出力 n 行"""
    lines = []
    for l in tail.splitlines():
        s = l.rstrip()
        if not s.strip() or SEPARATOR.match(s) or FOOTER.match(s):
            continue
        if s.startswith("❯") or NOISE.search(s) or AGENT_LINE.match(s):
            continue
        lines.append(s)
    return lines[-n:]


def sessions():
    """tmux セッション claude の各ウィンドウ = 1セッション"""
    out = []
    # -a を付けると -t が無視され、tmux サーバー上の全セッションを拾う(2026-09-24: 別セッションの砂場に本物のスレが混ざった)
    panes = shtmux(f"list-panes -s -t {TMUX_SESSION} -F '#{{window_name}}\t#{{pane_pid}}\t#{{pane_id}}\t#{{window_activity}}'")
    procs = {}
    for line in sh("ps -eo pid=,ppid=,etimes=,times=,args=").splitlines():
        p = line.split(None, 4)
        if len(p) == 5 and re.match(r"(\S*/)?claude --remote-control", p[4]):
            procs[p[1]] = {"pid": int(p[0]), "age_s": int(p[2]), "cpu_s": int(p[3]),
                           "name": p[4].split("--remote-control", 1)[1].strip().strip("'\"")}
    reg = load_registry()
    changed = False
    for line in panes.splitlines():
        try:
            win, ppid, pane, activity = line.split("\t")
        except ValueError:
            continue
        pr = procs.get(ppid)
        raw = shtmux(f"capture-pane -p -e -J -t {pane} -S -{FULL_LINES}")   # 色付き(ゴースト文字の判定用)
        tail = ANSI.sub("", raw)
        state, question = detect_state(tail, pr is not None)
        if state == "typed" and GHOST.search(raw):
            state = "idle"          # 入力欄の文字が薄字 = Claude の「次の候補」提案で、未送信の入力ではない
        if state == "typed":
            # 未送信の文そのものを載せる(2026-09-23)。司令室では「不明」としか出ず、
            # 何が溜まっているのか・消していいのかが使う側から判断できなかった。
            question = input_box_draft(raw)
        agents = detect_agents(tail) if pr else []
        if state == "idle" and agents:
            state = "working"       # サブエージェントが動いている間は本体が待っていても作業中
        # AskUserQuestion の複数質問(タブ形式)/確認画面を構造化する(単問はこれまで通り question のみ)
        choice = parse_choice(tail, raw) if state == "choice" else None
        if pr and reg.get(win, {}).get("name") != pr["name"]:
            reg[win] = {**reg.get(win, {}), "name": pr["name"], "last_seen": datetime.datetime.now(LOCAL).isoformat(timespec="seconds")}
            changed = True
        out.append({
            "window": win,
            "name": pr["name"] if pr else reg.get(win, {}).get("name", win),
            "pid": pr["pid"] if pr else None,
            "age_s": pr["age_s"] if pr else 0,
            "cpu_s": pr["cpu_s"] if pr else 0,
            "state": state,
            "question": question,
            "choice": choice,
            "last_activity_s": max(0, int(time.time()) - int(activity or 0)),
            "tail": last_output(tail, CARD_LINES),
            "agents": agents,
            "has_brief": bool(reg.get(win, {}).get("brief")),
        })
    if changed:
        save_registry(reg)
    return out


REGISTRY = C.REGISTRY


def load_registry():
    try:
        with open(REGISTRY, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_registry(reg):
    tmp = REGISTRY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=1)
    os.replace(tmp, REGISTRY)


def get_session_brief(window: str):
    return {"ok": True, "window": window, "brief": load_registry().get(window, {}).get("brief", "")}


def set_session_brief(window: str, brief: str):
    if not re.fullmatch(r"[\w\-]+", window or ""):
        return {"ok": False, "error": "bad window"}
    brief = (brief or "")[:4000]
    reg = load_registry()   # 他セッションが触ることがあるので直前に読み直す
    reg[window] = {**reg.get(window, {}), "brief": brief}
    save_registry(reg)
    log_action("brief-edit", window=window)
    return {"ok": True, "window": window, "brief": brief}


# 公開版は空(個人のスレ名・案件名を core にハードコードしない)。既定 brief を持たせたいスレが
# あるなら presets.json に "既定ブリーフ"(dict: window名 -> brief文)を足すか、sessions.json の
# 該当エントリへ直接 brief を書けばよい(下の ensure_default_briefs() は「無ければ埋める」だけ)。
DEFAULT_BRIEFS = {}


def ensure_default_briefs():
    """既定の brief を sessions.json に書き込む(brief が無いエントリにだけ追加。rc は対象外)。
    main は presets.json の「秘書(Main)」を、それ以外は presets.json の「既定ブリーフ」を見る
    (どちらも無ければ何もしない。DEFAULT_BRIEFS は個別に足したい場合の上書き用)。"""
    reg = load_registry()   # 他セッションが触ることがあるので直前に読み直す
    changed = False
    presets = load_presets()
    briefs = {**DEFAULT_BRIEFS, **presets.get("既定ブリーフ", {}), "main": presets.get("秘書(Main)", "")}
    for win, text in briefs.items():
        if win == "rc" or not text:
            continue
        if win in reg and not reg[win].get("brief"):
            reg[win]["brief"] = text
            changed = True
    if changed:
        save_registry(reg)
    return changed


def pane_full(window: str):
    if not re.fullmatch(r"[\w\-]+", window):
        return ""
    return shtmux(f"capture-pane -p -J -t {TMUX_SESSION}:{window} -S -{FULL_LINES}")


# ---------- 送信(v1) ----------
LOG_DIR = C.LOG_DIR


def window_exists(window: str) -> bool:
    if not re.fullmatch(r"[\w\-]+", window):
        return False
    return window in shtmux(f"list-windows -t {TMUX_SESSION} -F '#{{window_name}}'").split()


# 送信の直列化(2026-09-22)。送信元がプロセスをまたぐ(サーバー本体・Main が起動する単発
# python・各スレの生 tmux)ので threading.Lock では効かず、flock でウィンドウ単位に取る。
SEND_LOCK_WAIT = 9.0   # ロックが取れないときに待つ秒数。待っても取れなければ黙って送らずエラーにする
                       # (2026-09-23: 配達確認でロックを握る時間が伸びたので 5.0 から広げた)

# 配達確認(2026-09-23)。send-keys の Enter は**届かないことがある**。
# 実害: main の入力欄に未送信の文が溜まり、次の送信がその後ろにくっついて同じ文が2回入った。
# 使う側からは「未送信で不明状態」に見え、こちらには発言が届いていなかった。
# flock(9/22)は同時送信の混ざりを防ぐが、Enter の取りこぼしは防げない。送ったあと入力欄を読み、
# 空になっていなければ Enter を送り直す。それでも残るなら ok:false にして成功扱いにしない。
SEND_CONFIRM_WAITS = (0.5, 0.9, 1.4)   # Enter を送り直すまでに待つ秒数(この回数だけ試す)


def input_box_draft(raw: str) -> str:
    """入力欄に残っている未送信の文(無ければ '')。raw は色付きのまま渡すこと。
    ❯ の直後が薄字のときは Claude の「次の候補」提案なので未送信ではない(GHOST)。
    detect_state の typed 判定と同じ見方に揃えてある。"""
    tail = ANSI.sub("", raw)
    parts = SEPARATOR.split(tail)
    box = parts[-2] if len(parts) >= 3 else tail
    if PROMPT_EMPTY.search(box) or GHOST.search(raw):
        return ""
    if not re.search(r"^❯[\s ]*\S", box, re.M):
        return ""
    out, started = [], False
    for l in box.splitlines():
        if not started:
            m = re.match(r"^❯[\s ]*(.*)$", l)
            if m:
                started = True
                out.append(m.group(1))
            continue
        out.append(l)
    return "\n".join(x.rstrip() for x in out).strip()


def _pane_raw(window: str) -> str:
    return shtmux(f"capture-pane -p -e -J -t {TMUX_SESSION}:{window} -S -{FULL_LINES}")


def _confirm_delivered(window: str):
    """Enter が効いて入力欄が空になったかを確かめる。残っていれば Enter を送り直す。
    戻りは (届いたか, 残っている文)。**ロックを握ったまま呼ぶこと**(途中で他の送信が
    入力欄に文字を入れると、その文を送ってしまう)。"""
    for wait in SEND_CONFIRM_WAITS:
        time.sleep(wait)
        left = input_box_draft(_pane_raw(window))
        if not left:
            return True, ""
        # まだ残っている = Enter が届いていない。もう一度送る
        tmux("send-keys", "-t", f"{TMUX_SESSION}:{window}", "Enter", timeout=5)
    time.sleep(SEND_CONFIRM_WAITS[-1])
    left = input_box_draft(_pane_raw(window))
    return (not left), left


class _SendLockTimeout(Exception):
    pass


def _acquire_send_lock(window: str):
    """`{C.LOCK_DIR}/.send-<window>.lock` の flock を取って fd を返す。
    取れなければ SEND_LOCK_WAIT 秒まで待つ。呼び出し側は必ず try/finally で外し、fd を閉じること。"""
    os.makedirs(C.LOCK_DIR, exist_ok=True)
    fd = os.open(os.path.join(C.LOCK_DIR, f".send-{window}.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.time() + SEND_LOCK_WAIT
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except OSError:
            if time.time() >= deadline:
                os.close(fd)
                raise _SendLockTimeout()
            time.sleep(0.1)


def send(window: str, text: str, enter: bool = True, by: str = ""):
    """pane にテキストを流し込む。-l でリテラル送信し、Enter は別に送る(仕様: 2段送信)。
    2026-09-22: send-keys -l と Enter の両方をウィンドウ単位の flock で囲む。片方だけ囲んでも、
    その隙間に別プロセスの送信が割り込めば「片方の Enter がもう片方の文の途中で飛ぶ」事故は防げない。
    ロックが取れなければ黙って送らずエラーを返す(壊れた指示が飛ぶより、送れなかったと分かるほうがよい)。
    by は送り主の名前(ログ記録用。任意)。"""
    if not window_exists(window):
        return {"ok": False, "error": "no such window"}
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    if not text.strip() or len(text) > 4000:
        return {"ok": False, "error": "empty or too long"}
    try:
        fd = _acquire_send_lock(window)
    except _SendLockTimeout:
        return {"ok": False, "error": "ほかの送信中で順番が来ませんでした"}
    delivered, left, tries = True, "", 0
    try:
        tmux("send-keys", "-t", f"{TMUX_SESSION}:{window}", "-l", text, timeout=5)
        if enter:
            time.sleep(0.15)
            tmux("send-keys", "-t", f"{TMUX_SESSION}:{window}", "Enter", timeout=5)
            # 配達確認。入力欄が空になるまで Enter を送り直す(ロックは握ったまま)
            delivered, left = _confirm_delivered(window)
            tries = len(SEND_CONFIRM_WAITS)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    os.makedirs(LOG_DIR, exist_ok=True)
    day = now().strftime("%Y-%m-%d")
    with open(os.path.join(LOG_DIR, f"{day}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": now().isoformat(timespec="seconds"),
                            "window": window, "text": text, "enter": enter, "by": by,
                            **({} if delivered else {"delivered": False, "left": left[:200]})},
                           ensure_ascii=False) + "\n")
    if not delivered:
        # 黙って成功扱いにしない。入力欄に残っている分は画面(司令室)から消すか送るかを選べる
        return {"ok": False, "error": "Enter が届かず、入力欄に文が残っています(%d回送り直しました)" % tries,
                "left": left}
    return {"ok": True}


# ---------- 入力欄に残った未送信の文を送る/消す(2026-09-23) ----------
# 実測(使い捨ての Claude ウィンドウで確認。推測ではない):
#   C-u    … 待機中: 入力欄が空になる / 作業中: 中断しない。安全
#   Escape … 待機中: **何も起きない** / 作業中: **生成を中断し、処理中だった指示を入力欄に戻す**
#   C-c    … 待機中: 入力欄が空になる
# つまり消すのは C-u。Escape は「消す」には使えないうえ、作業中に送ると害が大きい。
# どちらの操作も、押したあとにペインを読み直して**本当に変わったか**を確かめる。
# 効かなかったときに黙って元の表示に戻ると、「押しても消えない」としか見えない。

def send_draft(window: str, by: str = ""):
    """入力欄に残っている未送信の文をそのまま送る(Enter)。配達確認つき。"""
    if not window_exists(window):
        return {"ok": False, "error": "no such window"}
    before = input_box_draft(_pane_raw(window))
    if not before:
        return {"ok": True, "sent": False, "note": "入力欄は既に空です"}
    try:
        fd = _acquire_send_lock(window)
    except _SendLockTimeout:
        return {"ok": False, "error": "ほかの送信中で順番が来ませんでした"}
    try:
        tmux("send-keys", "-t", f"{TMUX_SESSION}:{window}", "Enter", timeout=5)
        delivered, left = _confirm_delivered(window)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    log_action("draft-send" if delivered else "draft-send-failed",
               window=window, by=by, chars=len(before), **({} if delivered else {"left": left[:200]}))
    if not delivered:
        return {"ok": False, "error": "Enter が届かず、まだ入力欄に残っています", "left": left}
    return {"ok": True, "sent": True}


def clear_draft(window: str, by: str = ""):
    """入力欄に残っている未送信の文を消す(C-u)。消えたかを読み直して確かめる。"""
    if not window_exists(window):
        return {"ok": False, "error": "no such window"}
    raw = _pane_raw(window)
    state, _ = detect_state(ANSI.sub("", raw), True)
    if state == "working":
        # C-u 自体は作業中でも安全だが、作業中は入力欄の中身が動く(終了時に指示が戻ることがある)。
        # 消しても意味が無い場面なので押させない。
        return {"ok": False, "error": "作業中は消せません(終わってからにしてください)"}
    before = input_box_draft(raw)
    if not before:
        return {"ok": True, "cleared": False, "note": "入力欄は既に空です"}
    try:
        fd = _acquire_send_lock(window)
    except _SendLockTimeout:
        return {"ok": False, "error": "ほかの送信中で順番が来ませんでした"}
    cleared = False
    try:
        for wait in (0.4, 0.8):
            tmux("send-keys", "-t", f"{TMUX_SESSION}:{window}", "C-u", timeout=5)
            time.sleep(wait)
            if not input_box_draft(_pane_raw(window)):
                cleared = True
                break
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    if cleared:
        log_action("draft-clear", window=window, by=by, chars=len(before))
        return {"ok": True, "cleared": True}
    left = input_box_draft(_pane_raw(window))
    log_action("draft-clear-failed", window=window, by=by, left=left[:200])
    return {"ok": False, "error": "消せませんでした。入力欄に文が残っています", "left": left}


ALLOWED_KEYS = {"Enter", "Escape", "Up", "Down", "Tab", "y", "n", "C-u", "C-c", *[str(i) for i in range(10)]}


def log_action(kind, **kw):
    os.makedirs(LOG_DIR, exist_ok=True)
    day = datetime.datetime.now(LOCAL).strftime("%Y-%m-%d")
    with open(os.path.join(LOG_DIR, f"{day}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": datetime.datetime.now(LOCAL).isoformat(timespec="seconds"), "kind": kind, **kw}, ensure_ascii=False) + "\n")


def send_key(window: str, key: str):
    """単発のキー(Enter・Escape・数字など)を送る。仕様書の明文にはないが、send と同じロックを
    取らないと、ここから飛ぶ Enter が「もう片方の文の途中で飛ぶ Enter」になり得るため(2026-09-22)。"""
    if not window_exists(window):
        return {"ok": False, "error": "no such window"}
    if key not in ALLOWED_KEYS:
        return {"ok": False, "error": "key not allowed"}
    try:
        fd = _acquire_send_lock(window)
    except _SendLockTimeout:
        return {"ok": False, "error": "ほかの送信中で順番が来ませんでした"}
    try:
        tmux("send-keys", "-t", f"{TMUX_SESSION}:{window}", key, timeout=5)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    log_action("key", window=window, key=key)
    return {"ok": True}


def answer_choice(window: str, option: int, by: str = ""):
    """AskUserQuestion のピッカー(単問・複数問どちらも)で、いま出ている選択肢を1つ選ぶ。
    数字キーを1つだけ送る。Enter は送らない・送り直しもしない ── parse_choice() の説明コメントの
    通り、この「数字1つで即決定して次へ進む」画面に send() の Enter 送り直しを使うと、
    答えていない次の質問の推奨候補を黙って確定させてしまう事故になるため、専用の経路にしてある。"""
    if not window_exists(window):
        return {"ok": False, "error": "no such window"}
    try:
        n = int(option)
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad option"}
    if not (1 <= n <= 9):
        return {"ok": False, "error": "bad option"}
    try:
        fd = _acquire_send_lock(window)
    except _SendLockTimeout:
        return {"ok": False, "error": "ほかの送信中で順番が来ませんでした"}
    try:
        tmux("send-keys", "-t", f"{TMUX_SESSION}:{window}", str(n), timeout=5)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    log_action("choice", window=window, by=by, option=n)
    return {"ok": True}


def claude_bin():
    """systemd 経由だと PATH が細いので、claude の実体を自力で探す(nvm 配下も)"""
    import glob as _g
    cands = [shutil.which("claude"), os.path.expanduser("~/.local/bin/claude"), os.path.expanduser("~/.claude/local/claude")]
    def _ver(p):   # v24.9.0 が v24.21.0 より新しいと誤らないよう数値で比べる
        m = re.search(r"/v(\d+)\.(\d+)\.(\d+)/", p)
        return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)
    cands += sorted(_g.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/claude")), key=_ver, reverse=True)
    for c in cands:
        if c and os.access(c, os.X_OK):
            return c
    return "claude"


def pane_env():
    """新しいペインに渡す PATH(claude の場所と node を含める)"""
    b = os.path.dirname(claude_bin())
    return ["-e", f"PATH={b}:{os.path.expanduser('~/.local/bin')}:/usr/local/bin:/usr/bin:/bin"]


def claude_cmd(name: str):
    safe = name.replace("'", "").replace('"', "").replace("\\", "")
    return f"{claude_bin()} --remote-control '{safe}'; echo '[claude exited]'; exec bash"


PRESETS = C.PRESETS


def load_presets():
    try:
        with open(PRESETS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"なし": ""}


def send_when_idle(window: str, brief: str, max_wait_s: int = 60):
    """起動直後のスレが idle になった時点で brief を送る(送信ロジックはここ1本。new_session/restore_sessions/relaunch_session 共通)"""
    if not brief:
        return
    def _later():
        for _ in range(max(1, max_wait_s // 3)):
            time.sleep(3)
            s = next((x for x in sessions() if x["window"] == window), None)
            if s and s["state"] == "idle":
                send(window, brief, by="復帰brief")
                return
    threading.Thread(target=_later, daemon=True).start()


def new_session(name: str, preset: str = ""):
    name = name.strip()
    if not name or len(name) > 30 or any(c in name for c in "'\"\\;`$"):
        return {"ok": False, "error": "bad name"}
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:20]
    if not slug or slug.isdigit() or not slug[0].isalpha():
        slug = "s" + datetime.datetime.now(LOCAL).strftime("%H%M%S")   # 数字だけだとウィンドウ番号と衝突する
    if window_exists(slug):
        return {"ok": False, "error": f"window '{slug}' exists"}
    tmux("new-window", "-d", "-t", f"{TMUX_SESSION}:", "-n", slug, "-c", C.HOME, *pane_env(), claude_cmd(name), timeout=5)
    reg = load_registry()
    reg[slug] = {"name": name, "last_seen": datetime.datetime.now(LOCAL).isoformat(timespec="seconds")}
    save_registry(reg)
    log_action("new", window=slug, name=name, preset=preset)
    # preset は「その場で brief を決める」だけ(その内容を送るのは send_when_idle に統合済み)
    send_when_idle(slug, load_presets().get(preset, ""))
    return {"ok": True, "window": slug}


def restart_session(window: str, force: bool = False):
    """停止中のスレを立て直す。force=True なら動作中でも kill して立て直す(ログイン切れの復帰用)"""
    if not window_exists(window):
        return {"ok": False, "error": "no such window"}
    info = load_registry().get(window, {})
    for s in sessions():
        if s["window"] == window and s["pid"] and not force:
            # 動作中のスレの「再起動」は /clear で文脈だけ捨てる(2026-09-24。以前は still running で失敗していた)
            res = send(window, "/clear", by="再起動")
            if not res.get("ok"):
                return res
            log_action("clear", window=window, name=info.get("name", window))
            send_when_idle(window, info.get("brief", ""))
            return {"ok": True, "name": info.get("name", window), "cleared": True}
    name = info.get("name", window)
    tmux("respawn-pane", "-k", "-t", f"{TMUX_SESSION}:{window}", "-c", C.HOME, *pane_env(), claude_cmd(name), timeout=5)
    log_action("restart", window=window, name=name)
    return {"ok": True, "name": name}


# ---------- 単機能の専用セッション(window=docs など) ----------
def ensure_session(window: str, name: str, preset_key: str, max_wait_s: int = 90):
    """window が無ければ立ち上げてブリーフを送り、安定する(idle に戻る)まで待つ。
    既にあれば何もせず window 名だけ返す(server.py の各 /api/inquiry 系ジョブから使う)。
    new_session はスラッグを表示名から自動生成する(日本語名だとローマ字化できず定まらない)ため、
    ここでは window を固定しつつ表示名だけ日本語にしたい。そのため new_session をそのまま
    呼ぶのではなく、その内部部品(claude_cmd/pane_env/load_registry/save_registry/log_action/
    send_when_idle)を直接使って同じ手順を踏む。"""
    if window_exists(window):
        return {"ok": True, "window": window}
    tmux("new-window", "-d", "-t", f"{TMUX_SESSION}:", "-n", window,
                     "-c", C.HOME, *pane_env(), claude_cmd(name), timeout=5)
    reg = load_registry()
    reg[window] = {**reg.get(window, {}), "name": name, "last_seen": datetime.datetime.now(LOCAL).isoformat(timespec="seconds")}
    save_registry(reg)
    log_action("new", window=window, name=name, preset=preset_key)
    send_when_idle(window, load_presets().get(preset_key, ""))
    deadline = time.time() + max_wait_s
    seen_busy = False
    while time.time() < deadline:
        s = next((x for x in sessions() if x["window"] == window), None)
        if s:
            if s["state"] in ("working", "typed"):
                seen_busy = True
            elif s["state"] == "idle" and seen_busy:
                return {"ok": True, "window": window}
        time.sleep(2)
    return {"ok": True, "window": window, "warning": "timeout waiting idle"}


def ensure_docs_session(max_wait_s: int = 90):
    """「問い合わせで育つ説明書」専用セッション(window=docs)。ensure_session の薄いラッパー。"""
    return ensure_session("docs", "説明書", "説明書(docs)", max_wait_s)


# ---------- 運転モード: 送って返答を待って返す(Siri ショートカット用) ----------
TOOL = re.compile(r"^\s*(?:[●○◯]\s+)?(⎿|Reading\s|Writing\s|Editing\s|Searching\s|Running\s|Ran\s\d|Bash\(|Read\(|Write\(|Edit\(|Grep\(|Glob\(|Update\(|Fetch\(|Web(Search|Fetch)\()")


def _dw(s):
    return sum(2 if (ord(c) > 0x2E7F and not 0xFF61 <= ord(c) <= 0xFF9F) else 1 for c in s)


def unwrap(lines, cols=PANE_W if "PANE_W" in globals() else 100):
    """端末幅で折り返された行をつなぐ(ページ側と同じ規則)"""
    out = []
    end = re.compile(r"([。．.!?！？:：」』)]|です|ます|でした|ません|ました)\s*$")
    mark = re.compile(r"^\s*([-*•●○◦✻✶✳✢·⎿└├│┃]|\d+[.)]\s|#{1,4}\s|> )")
    for l in lines:
        s = re.sub(r"^\s{1,6}", "", l)
        if out and _dw(out[-1][1]) >= cols * 0.88 and not end.search(out[-1][1]) and not mark.match(l):
            join = " " if (out[-1][0][-1:].isascii() and s[:1].isascii()) else ""
            out[-1] = (out[-1][0] + join + s, l)
        else:
            out.append((s, l))
    return [o[0] for o in out]


def extract_reply(pane_text: str, sent: str):
    """自分の発言の写し(❯ …)の後ろを返答として取り出す。
    複数行の発言(メール本文など)は画面上、最初の行だけが ❯ 付きで描かれ、続きは別行になるため、
    照合キーは先頭行だけから作る(全文から作ると1行目に収まらず一致しない)。"""
    raw = [l.rstrip() for l in ANSI.sub("", pane_text).splitlines()]
    key = re.sub(r"\s+", "", sent.split("\n", 1)[0])[:18]
    start = -1
    for k in range(len(raw) - 1, -1, -1):
        if re.match(r"^❯\s+\S", raw[k]) and key in re.sub(r"\s+", "", raw[k]):
            start = k + 1
            break
    if start < 0:
        return None
    body = [l for l in raw[start:] if l.strip() and not FOOTER.match(l) and not SEPARATOR.match(l)
            and not NOISE.search(l) and not TOOL.match(l) and not l.lstrip().startswith("❯")]
    text = "\n".join(unwrap(body))
    return re.sub(r"^[│┃●]\s?", "", text, flags=re.M)


def ask(window: str, text: str, timeout: int = 55, by: str = ""):
    """送信して、返答が出そろう(待機に戻る)まで待ち、返答テキストを返す。timeout 秒で打ち切り(途中までを返す)。
    送信自体は send() を経由するので同じロックを通る。待機ループ(最大55秒)はロックの外(2026-09-22)。"""
    res = send(window, text, by=by)
    if not res.get("ok"):
        return res
    deadline = time.time() + timeout
    idle = 0
    reply = ""
    while time.time() < deadline:
        time.sleep(2)
        pane = shtmux(f"capture-pane -p -e -J -t {TMUX_SESSION}:{window} -S -{FULL_LINES}")
        r = extract_reply(pane, text)
        if r:
            reply = r
        state, _ = detect_state(ANSI.sub("", pane), True)
        if state == "typed" and GHOST.search(pane):
            state = "idle"
        idle = idle + 1 if (state == "idle" and reply) else 0
        if idle >= 2:
            return {"ok": True, "reply": reply, "done": True}
    return {"ok": True, "reply": reply or "(まだ返答がありません)", "done": False}


# ---------- 通知: 状態遷移を検知して Web Push ----------
_prev = {}          # window -> {"state","since","name"}
_last_notified = {} # key -> ts
NEED = {"approval", "trust", "choice", "login"}


SURVEY = re.compile(r"How is Claude doing this session")


def auto_dismiss(sess):
    """満足度アンケート(任意)は自動で閉じる。要対応の通知にも乗せない"""
    for s in sess:
        if s["state"] == "choice" and SURVEY.search(s.get("question") or ""):
            tmux("send-keys", "-t", f"{TMUX_SESSION}:{s['window']}", "0")
            log_action("dismiss-survey", window=s["window"])
            s["state"] = "idle"; s["question"] = ""


def notify_check(sess=None):
    """前回との差分から通知イベントを作る。戻り値: [(title, body, tag)]"""
    now = time.time()
    events = []
    sess = sess if sess is not None else sessions()
    auto_dismiss(sess)
    seen = set()
    for s in sess:
        w = s["window"]; seen.add(w)
        st = s["state"]; name = s["name"]
        p = _prev.get(w)
        if p is None:
            _prev[w] = {"state": st, "since": now, "name": name}
            continue
        if st != p["state"]:
            if st in NEED:
                q = (s.get("question") or "").splitlines()
                events.append((f"要対応: {name}", (q[0] if q else st)[:120], f"need-{w}", w))
            elif st == "dead":
                events.append((f"停止: {name}", "セッションが終了しました。カードから再起動できます", f"dead-{w}", w))
            elif st == "idle" and p["state"] == "working" and now - p["since"] >= 20:
                last = (s.get("tail") or [""])[-1]
                events.append((f"完了: {name}", last[:120], f"done-{w}", w))
            _prev[w] = {"state": st, "since": now, "name": name}
    for w in list(_prev):
        if w not in seen:
            events.append((f"消滅: {_prev[w]['name']}", "ウィンドウが無くなりました", f"gone-{w}", w))
            del _prev[w]
    out = []
    for title, body, tag, w in events:
        if now - _last_notified.get(tag, 0) < 60:
            continue
        _last_notified[tag] = now
        out.append((title, body, tag, w))
    return out


# ---------- v3: 日次まとめ / 復帰 ----------
VAULT_DAILY = C.vault_path("daily")
DAILY_MARK = os.path.join(LOG_DIR, "daily-%s.state")   # 当日の実行状態(試行回数・done)


DIGEST_LINES = 120   # 1セッションあたり digest に載せる最大行数


def write_digest(day: str):
    """Main に読ませる材料を1ファイルにまとめる(ツール呼び出し1回で済ませ、ノイズ行を落としてトークンを節約)"""
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"digest-{day}.md")
    parts = [f"# digest {day}\n"]
    try:
        with open(os.path.join(LOG_DIR, f"{day}.jsonl"), encoding="utf-8") as f:
            sent = [json.loads(l) for l in f if l.strip()]
        sent = [e for e in sent if e.get("text")]
        if sent:
            parts.append("## 司令室から送った指示\n" + "\n".join(f"- {e['ts'][11:16]} → {e['window']}: {e['text'][:200]}" for e in sent) + "\n")
    except OSError:
        pass
    for s in sessions():
        raw = ANSI.sub("", shtmux(f"capture-pane -p -J -t {TMUX_SESSION}:{s['window']} -S -{FULL_LINES}"))
        lines = last_output(raw, DIGEST_LINES)
        # 連続する重複行を潰す
        dedup = [l for i, l in enumerate(lines) if i == 0 or l != lines[i-1]]
        body = "\n".join(dedup) if dedup else "(出力なし)"
        parts.append(f"## {s['name']} (window={s['window']}, state={s['state']}, 生存 {s['age_s']//3600}h)\n```\n{body}\n```\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return path


def daily_prompt(day: str):
    digest = write_digest(day)
    return (f"今日({day})の日次まとめを書いてください。材料は {digest} の1ファイルだけです(司令室から送った指示と、各セッションの画面末尾を整理済み)。"
            f"他のファイルやコマンドは読まなくて構いません。"
            f"出力先は {VAULT_DAILY}/{day}.md。frontmatter に date: {day} と sessions:(セッション表示名の配列)。"
            f"見出しはセッション別(H2=セッション名)で、その下に「やったこと」「決めたこと」「明日」をH3。ですます調、箇条書き可、1セッション8行以内。"
            f"材料が乏しいセッションは「動きなし」とだけ書く。書き終えたら『done』とだけ返してください。")


def _daily_state(day):
    try:
        with open(DAILY_MARK % day, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"tries": 0, "done": False}


def _save_daily_state(day, st):
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(DAILY_MARK % day, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)


def daily_summary(force=False):
    """Main が待機中なら日次まとめのプロンプトを送る。戻り値は結果の説明"""
    day = datetime.datetime.now(LOCAL).strftime("%Y-%m-%d")
    st = _daily_state(day)
    if st["done"] and not force:
        return {"ok": True, "skipped": "already done"}
    if st["tries"] >= 3 and not force:
        return {"ok": False, "error": "gave up (3 tries)"}
    main = next((s for s in sessions() if s["name"] == "Main" or s["window"] == "main"), None)
    if not main or not main["pid"]:
        return {"ok": False, "error": "Main not running"}
    if main["state"] != "idle":
        st["tries"] += 1
        _save_daily_state(day, st)
        return {"ok": False, "error": f"Main is {main['state']}", "retry": True}
    os.makedirs(VAULT_DAILY, exist_ok=True)
    res = send(main["window"], daily_prompt(day), by="日次まとめ")
    if res.get("ok"):
        st["done"] = True
        st["sent_at"] = datetime.datetime.now(LOCAL).isoformat(timespec="seconds")
        _save_daily_state(day, st)
        log_action("daily", window=main["window"], day=day)
    return res


def daily_text():
    day = datetime.datetime.now(LOCAL).strftime("%Y-%m-%d")
    path = os.path.join(VAULT_DAILY, f"{day}.md")
    st = _daily_state(day)
    try:
        with open(path, encoding="utf-8") as f:
            return {"date": day, "exists": True, "text": f.read(), "state": st}
    except OSError:
        return {"date": day, "exists": False, "text": "", "state": st}


PANE_W, PANE_H = 100, 120   # 誰も接続していない間の描画サイズ。Claude Code は代替スクリーンで履歴が残らないので、縦を広げて過去の出力を見えるようにする


def ensure_window_size():
    """クライアント未接続なら全ウィンドウを PANE_W x PANE_H に。接続中は触らない(端末サイズ優先)"""
    if shtmux(f"list-clients -t {TMUX_SESSION}").strip():
        return False
    changed = False
    for line in shtmux(f"list-windows -t {TMUX_SESSION} -F '#{{window_id}} #{{window_width}} #{{window_height}}'").splitlines():
        try:
            wid, w, h = line.split()
        except ValueError:
            continue
        if int(w) != PANE_W or int(h) != PANE_H:
            tmux("resize-window", "-t", wid, "-x", str(PANE_W), "-y", str(PANE_H), timeout=5)
            changed = True
    return changed


def read_log(day: str):
    try:
        with open(os.path.join(LOG_DIR, f"{day}.jsonl"), encoding="utf-8") as f:
            return [json.loads(l) for l in f if l.strip()]
    except OSError:
        return []


def past_sessions():
    """名簿にあって今は無いスレ(立て直し候補)"""
    present = set(shtmux(f"list-windows -t {TMUX_SESSION} -F '#{{window_name}}'").split())
    return [{"window": w, "name": i.get("name", w), "last_seen": i.get("last_seen", ""), "auto": i.get("auto", True),
             "has_brief": bool(i.get("brief"))}
            for w, i in load_registry().items() if w not in present and i.get("name")]


def relaunch_session(window: str):
    """過去のスレを同じウィンドウ名・表示名で立て直し、復帰対象に戻す"""
    reg = load_registry()
    info = reg.get(window)
    if not info:
        return {"ok": False, "error": "not in registry"}
    if window_exists(window):
        return {"ok": False, "error": "already exists"}
    tmux("new-window", "-d", "-t", f"{TMUX_SESSION}:", "-n", window, "-c", C.HOME, *pane_env(), claude_cmd(info["name"]), timeout=5)
    info["auto"] = True
    info["last_seen"] = datetime.datetime.now(LOCAL).isoformat(timespec="seconds")
    save_registry(reg)
    log_action("relaunch", window=window, name=info["name"])
    send_when_idle(window, info.get("brief", ""))
    return {"ok": True, "window": window, "name": info["name"]}


def restore_sessions():
    """名簿にあって tmux に無いウィンドウを立て直す(rc は start-claude.sh の担当なので除外)。
    tmux セッション自体が無いうちは何もしない(start-claude.sh がまだ走っていない)。"""
    if tmux("has-session", "-t", TMUX_SESSION, capture_output=True).returncode != 0:
        return []
    present = set(shtmux(f"list-windows -t {TMUX_SESSION} -F '#{{window_name}}'").split())
    restored = []
    for win, info in load_registry().items():
        if win == "rc" or win in present or not info.get("name") or info.get("auto") is False:
            continue
        tmux("new-window", "-d", "-t", f"{TMUX_SESSION}:", "-n", win, "-c", C.HOME, *pane_env(), claude_cmd(info["name"]), timeout=5)
        log_action("restore", window=win, name=info["name"])
        send_when_idle(win, info.get("brief", ""))
        restored.append(win)
        time.sleep(3)   # 同時起動で信頼フラグの書き戻し競合を避ける
    return restored


def forget_session(window: str):
    """復帰対象から外す(名簿には「過去のスレ」として残す)。停止中ならウィンドウも閉じる"""
    reg = load_registry()
    if window in reg:
        reg[window]["auto"] = False
        save_registry(reg)
    if window_exists(window) and not any(s["pid"] for s in sessions() if s["window"] == window):
        tmux("kill-window", "-t", f"{TMUX_SESSION}:{window}", timeout=5)
    log_action("forget", window=window)
    return {"ok": True}


def stop_session(window: str, by: str = ""):
    """スレを止める(動作中でも閉じる。2026-09-22 §司令室の入口)。
    順番が要: **auto=False を先に書いてから** kill-window する。
    逆にすると、毎分走る restore_sessions() が名簿を見て立て直してしまう。
    rc は restore_sessions() の対象外(start-claude.sh の担当)なので、止めてもログオンで戻る。"""
    reg = load_registry()
    if window in reg:
        reg[window]["auto"] = False
        save_registry(reg)   # ここが先。kill-window より前に auto=False を書き終える
    killed = False
    if window_exists(window):
        tmux("kill-window", "-t", f"{TMUX_SESSION}:{window}", timeout=5)
        killed = True
    # by = 誰が止めたか(2026-09-22)。記録が無いと、後から「誰がこのスレを落としたか」を
    # 追えない。実際にあるスレが止まった回で、司令室からの操作か別の経路かを切り分けられず、
    # 取り違えて報告した。send と同じく送り主を残す。
    log_action("stop", window=window, by=by)
    return {"ok": True, "window": window, "killed": killed}


# ---------- v4: 朝の便り / 期限リマインドの材料集め(送信・保存は server.py) ----------
def yesterday_highlights(max_n=4):
    """昨日の日次まとめ(vault/daily/<昨日>.md)から、各セッションの「やったこと」1行目を拾う"""
    day = (now().date() - datetime.timedelta(days=1)).isoformat()
    path = os.path.join(VAULT_DAILY, f"{day}.md")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().split("\n")
    except OSError:
        return day, []
    out, name = [], None
    for i, l in enumerate(lines):
        m = re.match(r"^##\s+(.*)", l)
        if m:
            name = m.group(1).strip()
            continue
        if name and re.match(r"^###\s*やったこと", l):
            for j in range(i + 1, len(lines)):
                s = lines[j].strip()
                if not s:
                    continue
                out.append((name, re.sub(r"^[-*]\s*", "", s)))
                break
            name = None
    return day, out[:max_n]


def brief_text():
    """当日の朝の便り(vault/daily/brief-YYYY-MM-DD.md)の本文"""
    day = now().strftime("%Y-%m-%d")
    path = os.path.join(VAULT_DAILY, f"brief-{day}.md")
    try:
        with open(path, encoding="utf-8") as f:
            return {"date": day, "exists": True, "text": f.read()}
    except OSError:
        return {"date": day, "exists": False, "text": ""}


def collect():
    with open("/proc/uptime") as f:
        up = float(f.read().split()[0])
    l1, l5, l15 = os.getloadavg()
    total, used = meminfo()
    du = shutil.disk_usage("/")
    return {
        "ts": now().isoformat(timespec="seconds"),
        "uptime_s": int(up),
        "load": [round(l1, 2), round(l5, 2), round(l15, 2)],
        "ncpu": os.cpu_count() or 1,
        "cpu_pct": cpu_percent(),
        "mem_pct": round(100 * used / total, 1),
        "mem_used_gb": round(used / 2**30, 2),
        "mem_total_gb": round(total / 2**30, 1),
        "disk_pct": round(100 * du.used / du.total, 1),
        "procs": int(sh("ls /proc | grep -c '^[0-9]'") or 0),
        "sessions": sessions(),
        "cols": PANE_W,
        "peers": tailscale_peers(),
        "host": os.uname().nodename,
    }


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=1))
