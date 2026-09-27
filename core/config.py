"""設定の読み込み口(1本化)。値はリポジトリ直下の config.toml から読む。

- config.toml が無ければ config.example.toml を読む(初回起動でも落ちない)。
- 環境変数 TINY_PULSE_CONFIG で別の toml を指せる(並走・テスト用)。
- 旧来の環境変数(TINY_PULSE_PORT など)は config より優先する(既存の systemd 設定を壊さないため)。
- パスは「~」を展開する。相対パスは APP_DIR(このリポジトリ)基準、vault 配下は vault_path() で引く。

使い方: `from core import config as C` → `C.PORT`, `C.LOG_DIR`, `C.vault_path("plan")` など。
"""
import os
import tomllib

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load():
    path = os.environ.get("TINY_PULSE_CONFIG") or os.path.join(APP_DIR, "config.toml")
    if not os.path.exists(path):
        path = os.path.join(APP_DIR, "config.example.toml")
    with open(path, "rb") as f:
        return path, tomllib.load(f)


CONFIG_PATH, RAW = _load()


def get(section, key, default=None):
    return RAW.get(section, {}).get(key, default)


def _path(p):
    p = os.path.expanduser(str(p))
    return p if os.path.isabs(p) else os.path.normpath(os.path.join(APP_DIR, p))


def _env(name, default, cast=str):
    v = os.environ.get(name)
    return cast(v) if v not in (None, "") else default


def _hm(s):
    h, m = str(s).split(":")
    return int(h), int(m)


# ---- 場所 ----
HOME = _path(get("paths", "home", "~"))                  # 新しいスレの作業ディレクトリ(tmux -c)
VAULT = os.path.realpath(_path(get("paths", "vault", "~/vault")))
DATA_DIR = _path(get("paths", "data_dir", "."))          # sessions.json / push.json / presets.json の置き場
LOG_DIR = _path(get("paths", "log_dir", "log"))
INBOX = _path(get("paths", "inbox", "inbox"))
CERT_DIR = _path(get("paths", "cert_dir", "certs"))
# 送信ロック(flock)の置き場。旧版と並走する間は旧版の log を指し、同じウィンドウへの同時送信を防ぐ
LOCK_DIR = _path(get("paths", "lock_dir", LOG_DIR))
REGISTRY = os.path.join(DATA_DIR, "sessions.json")
PUSH_STORE = os.path.join(DATA_DIR, "push.json")
PRESETS = os.path.join(DATA_DIR, "presets.json")
CLAUDE_CREDENTIALS = _path(get("paths", "claude_credentials", "~/.claude/.credentials.json"))

# 公開の room(plan/workout/daily/docs)の既定だけをここに持つ。rooms-private 側の room が
# vault_path()/vault_rel() を独自の名前(例: 案件名)で呼ぶ場合は、config.toml の [vault] に
# 同じキーで値を書けば拾える(そちらに無ければ最後は名前そのものを相対パスとして使う)。
_VAULT_DEFAULTS = {
    "plan": "plan",
    "workout_log": "workout/log.md",
    "daily": "daily",
    "docs": "docs-inquiry",
}


def vault_rel(name):
    """vault からの相対パス(例: "plan")。safe_path() に渡す用"""
    return get("vault", name, _VAULT_DEFAULTS.get(name, name))


def vault_path(name):
    """vault 配下の絶対パス。config の [vault] で上書きでき、絶対パスも書ける"""
    rel = os.path.expanduser(vault_rel(name))
    return rel if os.path.isabs(rel) else os.path.join(VAULT, rel)


# ---- サーバ ----
BIND = _env("TINY_PULSE_BIND", get("server", "bind", "127.0.0.1"))
PORT = _env("TINY_PULSE_PORT", int(get("server", "port", 8787)), int)
HTTPS_PORT = _env("TINY_PULSE_HTTPS_PORT", int(get("server", "https_port", 8443)), int)
HOSTNAME = get("server", "hostname", "")                 # Tailscale の証明書を取る名前(空なら HTTPS なし)
PUSH_SUBJECT = get("server", "push_subject", "https://example.com")

# ---- tmux / claude ----
TMUX_SESSION = get("tmux", "session", "claude")

# ---- 並走スイッチ(旧版と同時に動かす間は false にして二重動作を防ぐ) ----
JOBS_ENABLED = bool(get("features", "jobs", True))          # 定時ジョブ(日次まとめ・brief・remind など)
AUTO_RESTORE = bool(get("features", "auto_restore", True))  # 名簿からの自動復帰
PUSH_ENABLED = bool(get("features", "push", True))          # 状態遷移の自動通知(テスト送信は常に可)

# ---- 定時 ----
DAILY_HOUR, DAILY_MIN = _hm(_env("TINY_PULSE_DAILY_AT", get("schedule", "daily", "21:30")))
NUMBERS_HOUR, NUMBERS_MIN = _hm(_env("TINY_PULSE_NUMBERS_AT", get("schedule", "numbers", "07:15")))
WEEKLY_HOUR, WEEKLY_MIN = _hm(_env("TINY_PULSE_WEEKLY_AT", get("schedule", "weekly", "08:30")))
SLOT_NOTICE_HOUR, SLOT_NOTICE_MIN = _hm(_env("TINY_PULSE_SLOT_NOTICE_AT", get("schedule", "slot_notice", "20:00")))
BRIEF_HOUR, BRIEF_MIN = _hm(get("schedule", "brief", "07:30"))
REMIND_HOURS = [int(h) for h in get("schedule", "remind_hours", [8, 18])]
LOGIN_CHECK_HOUR = int(get("schedule", "login_check_hour", 9))
# room 固有の設定は各 room が get(section, key, default) / hm() / path() で自分で読む(core は room の名前を知らない)
hm = _hm
path = _path
