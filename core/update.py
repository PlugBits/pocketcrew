#!/usr/bin/env python3
"""Claude Code(npm の @anthropic-ai/claude-code)の更新を確認・適用する(標準ライブラリのみ)。
このマシンは自動アップデートを止めてある(~/.claude/settings.json の DISABLE_AUTOUPDATER)。
代わりに司令室が「更新あり」を見せ、ユーザーがタップした時だけ npm install --global で入れる。
状態は log/update.json に保存する。"""
import os, sys, json, time, threading, subprocess, datetime

# core/update.py が単体で読み込まれても "core" パッケージが見えるように、
# リポジトリ直下(このファイルの2つ上)を sys.path に足す
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config as C
from core import collect
try:
    from core import webpush
except Exception:   # cryptography が無い環境でも update.py 単体は動く
    webpush = None

STATE_PATH = os.path.join(C.LOG_DIR, "update.json")
PKG = "@anthropic-ai/claude-code"
CHECK_INTERVAL_S = 6 * 3600
_lock = threading.Lock()


def _load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_state(st):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE_PATH)


def _npm_dir():
    """claude と同じ bin ディレクトリ(nvm 配下)"""
    return os.path.dirname(collect.claude_bin())


def _npm_bin():
    return os.path.join(_npm_dir(), "npm")


def _npm_env():
    """systemd の PATH には nvm が無いので先頭に足す(collect.pane_env() と同じ考え方)"""
    env = os.environ.copy()
    env["PATH"] = _npm_dir() + os.pathsep + env.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    return env


def installed_version():
    """claude の実体(claude.exe)の2つ上の package.json の version。読めなければ `claude --version` の先頭トークン。"""
    try:
        real = os.path.realpath(collect.claude_bin())
        pkg = os.path.join(os.path.dirname(os.path.dirname(real)), "package.json")
        with open(pkg, encoding="utf-8") as f:
            v = json.load(f).get("version")
        if v:
            return v
    except Exception:
        pass
    try:
        out = collect.sh(f'"{collect.claude_bin()}" --version', timeout=10).strip()
        tok = out.split()[0] if out else ""
        return tok or None
    except Exception:
        return None


def _is_newer(latest, installed):
    """latest/installed が両方あって違う時だけ True 候補。数字で比較できれば latest > installed の時だけ True、
    できなければ違うというだけで True。"""
    if not latest or not installed or latest == installed:
        return False
    try:
        lt = tuple(map(int, latest.split(".")))
        it = tuple(map(int, installed.split(".")))
        return lt > it
    except Exception:
        return True


def check(force=False):
    """npm view --prefer-online(30秒)。6時間以内にチェック済みで force=False なら状態ファイルをそのまま返す。
    失敗しても例外を上げず、前回値を返す。"""
    with _lock:
        st = _load_state()
    if not force and st.get("checked"):
        try:
            last = datetime.datetime.fromisoformat(st["checked"])
            if (collect.now() - last).total_seconds() < CHECK_INTERVAL_S:
                return st
        except Exception:
            pass
    try:
        out = subprocess.run(
            [_npm_bin(), "view", PKG, "version", "--prefer-online"],
            capture_output=True, text=True, timeout=30, env=_npm_env(),
        ).stdout.strip()
        if out:
            st["latest"] = out
    except Exception:
        pass
    st["checked"] = collect.now().isoformat(timespec="seconds")
    with _lock:
        _save_state(st)
    return st


def state():
    """npm を呼ばない軽い状態。status() に同梱するためのもの。"""
    st = _load_state()
    installed = installed_version()
    latest = st.get("latest")
    return {
        "installed": installed,
        "latest": latest,
        "available": _is_newer(latest, installed),
        "checked": st.get("checked"),
        "running": bool(st.get("running")),
        "last": st.get("last"),
    }


def _push(ok, installed, latest, error, ts):
    if not webpush:
        return
    try:
        if webpush.get_level() == "need" or not webpush.subscriptions():
            return
        if ok:
            webpush.broadcast("Claude 更新完了", f"{installed} → {latest}。スレを再起動すると反映", "/", f"update-{ts}")
        else:
            webpush.broadcast("Claude 更新失敗", str(error or "")[:200], "/", f"update-{ts}")
    except Exception:
        pass


def _apply_thread(installed, latest, npm_cmd):
    ts = collect.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(C.LOG_DIR, f"update-{ts}.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    cmd = npm_cmd if npm_cmd else [_npm_bin(), "install", "--global", f"{PKG}@{latest}"]
    use_shell = isinstance(cmd, str)

    def run_once():
        with open(log_path, "a", encoding="utf-8") as log:
            try:
                subprocess.run(cmd, shell=use_shell, stdout=log, stderr=subprocess.STDOUT, timeout=600, env=_npm_env())
            except Exception as e:
                log.write(f"\n[error] {e}\n")

    run_once()
    new_installed = installed_version()
    real = os.path.realpath(collect.claude_bin())
    ok = (new_installed == latest)
    error = None if ok else f"version unchanged: {new_installed}"
    if not ok or not os.path.exists(real):
        # 中断で退避(retire)された claude が復元されないケースの復旧。もう1回だけ試す
        run_once()
        new_installed = installed_version()
        ok = (new_installed == latest)
        error = None if ok else f"version unchanged: {new_installed}"

    collect.log_action("update", ok=ok, **{"from": installed, "to": latest, "error": error or ""})
    with _lock:
        st = _load_state()
        st["running"] = False
        st["last"] = {"ts": collect.now().isoformat(timespec="seconds"), "ok": ok, "from": installed, "to": latest, "error": error, "log": log_path}
        _save_state(st)
    _push(ok, installed, latest, error, ts)


def apply(npm_cmd=None, force=False):
    """既に running なら拒否。latest が無ければ拒否。latest == installed かつ force でなければ「already latest」で拒否
    (テスト用に --force で進められる)。それ以外はスレッドを起こして即座に返す。"""
    with _lock:
        st = _load_state()
        if st.get("running"):
            return {"ok": False, "error": "running"}
        latest = st.get("latest")
        installed = installed_version()
        if not latest:
            return {"ok": False, "error": "no latest known(check未実施)"}
        if not force and installed and latest == installed:
            return {"ok": False, "error": "already latest"}
        st["running"] = True
        _save_state(st)
    threading.Thread(target=_apply_thread, args=(installed, latest, npm_cmd), daemon=True).start()
    return {"ok": True, "started": True, "from": installed, "to": latest}


def notify_available():
    """scheduler から毎分呼ぶ(check が6時間キャッシュなので実質6時間ごとに意味を持つ)。
    available かつ未通知なら level=all の時だけ Push。level に関わらず notified は進める
    (後で level を変えても同じ版で二重に鳴らさないため)。"""
    st = _load_state()
    latest = st.get("latest")
    installed = installed_version()
    if not _is_newer(latest, installed) or st.get("notified") == latest:
        return
    if webpush:
        try:
            if webpush.get_level() == "all" and webpush.subscriptions():
                webpush.broadcast(f"Claude {latest} が出ています", f"司令室の「適用」で入ります(今は {installed})", "/", f"update-avail-{latest}")
        except Exception:
            pass
    with _lock:
        st = _load_state()
        st["notified"] = latest
        _save_state(st)


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    cmd = args[0] if args else "state"
    if cmd == "state":
        print(json.dumps(state(), ensure_ascii=False, indent=1))
    elif cmd == "check":
        print(json.dumps(check(force=True), ensure_ascii=False, indent=1))
    elif cmd == "apply":
        npm_cmd = None
        force = "--force" in args
        if "--npm" in args:
            npm_cmd = args[args.index("--npm") + 1]
        res = apply(npm_cmd=npm_cmd, force=force)
        print(json.dumps(res, ensure_ascii=False, indent=1))
        if res.get("started"):
            while state()["running"]:
                time.sleep(0.5)
            print(json.dumps(state(), ensure_ascii=False, indent=1))
    else:
        print("usage: update.py state|check|apply [--npm \"<cmd>\"] [--force]")
