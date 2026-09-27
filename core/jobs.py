"""room 共有の非同期ジョブキュー(旧: 各 room が個別に持っていた inquiry queue を1本化)。

iPhone の画面ロック/アプリ切替で fetch が切れるので、時間のかかる処理(docs スレへの質問、
その他 room の AI 呼び出しなど)は同期で待たず、ジョブを積んで即座に {job: <id>} を返す。
GET /api/inquiry/<id> (または /api/jobs/<id>)で後から結果を取る。

room は import 時に register() で自分の kind を登録する(room 同士は import しないので、
core 経由でこのキューを共有する)。1本のワーカースレッドが順番に処理する(docs スレの tmux 送信など、
同じ外部リソースに複数の kind が同時に触らないよう、意図して直列)。

  register(kinds, runner, on_done=None)
      kinds   : str、または str のリスト/タプル(1つでも複数でもよい)
      runner  : runner(job: dict) -> dict   {"ok": bool, "done": bool, ...}(旧 _run_*_sync と同じ形)
      on_done : on_done(job_copy: dict)     ジョブが done/failed になった直後に呼ばれる(成功・失敗どちらも)。
                省略可。ここで例外が出ても握りつぶす(1つの登録側の通知処理が他に影響しないように)。
  create(kind, text, timeout, extra=None) -> dict   ジョブを作ってキューに積み、即座に返す({"id":...} 等)
  get(job_id) -> dict | None             ジョブの現在値(コピー)
  recent(kind, n=3) -> list[dict]        指定 kind で status=="done" のものを新しい順に n 件
  new_id() -> str                        ジョブID(同期呼び出しの job_id 引数にも使う)
  access_log(handler, status, ct="", blen=0, kind="", text="", note="", raw=b"")
                                          /api/inquiry* へのアクセスログ(旧 inquiry_access_log)
  JOBS: dict[str, dict]                  id -> job(起動時に JOBS_LOG から復元。既存コードはこれを直接見てよい)
  JOBS_LOCK: threading.Lock              JOBS を触るときはこれで守る
  worker()                               ワーカー本体。core/server.py の main() がスレッドで起動する

---------- POST/GET /api/inquiry(裸パス。room 共有・段階C) ----------
docs(add/ask/rewrite/fix)・その他 room 固有の kind 一覧(各 room が register() で登録)は同じ裸の /api/inquiry から入る
(各 room の JS が自分の kind を直接 POST、iOS ショートカットが add/ask 等を POST する)。
本文の正規化(normalize_inquiry_body)・アクセスログ・ディスパッチは core が持ち、kind ごとの
検証+ジョブ作成(旧 api_inquiry の各 if/elif 分岐)は room 側が register() の accept= で登録する。

  register(kinds, runner, on_done=None, accept=None)
      accept: accept(body: dict) -> dict     kind ごとの検証+ジョブ作成(旧 api_inquiry の分岐と
              同じ戻り値をそのまま返す)。省略した kind は api_inquiry() からは呼ばれない
              (ジョブの実行・通知だけを持つ kind 用。今のところ全 kind が accept を持つ)。
  register_default_accept(fn)              上のどの kind にも一致しなかったとき(add/ask も含む。
              旧 api_inquiry の最後の else 分岐)に呼ぶ既定ハンドラ。docs room が登録する。
  validate_photos(photos, inbox_dir)       /api/upload が返したパスを検証する(inbox 配下・許可
              拡張子・実在するものだけ、最大 MAX_PHOTOS 件)。旧 core/server.py・docs の
              _validate_photos と同一ロジック(room 間の重複を避けて core に1本化)。
  normalize_inquiry_body(body) -> dict      ショートカット由来のゆるい本文を {kind,text,path,photos,...} に揃える
  api_inquiry(body) -> dict                 正規化 → kind から accept を引いて呼ぶ(core/server.py の
              POST /api/inquiry がそのまま返す)
"""
import json
import os
import queue
import threading
import time
import uuid

from core import config as C
from core import collect

JOBS_LOG = os.path.join(C.LOG_DIR, "inquiry-jobs.jsonl")
ACCESS_LOG = os.path.join(C.LOG_DIR, "inquiry-access.jsonl")

_QUEUE = queue.Queue()
JOBS_LOCK = threading.Lock()

_RUNNERS = {}   # kind -> runner(job) -> dict
_ON_DONE = {}   # kind -> on_done(job_copy) | None
_ACCEPT = {}    # kind -> accept(body) -> dict(/api/inquiry のディスパッチ用)
_DEFAULT_ACCEPT = [None]   # register_default_accept() が1つだけ入れる(docs room)


def register(kinds, runner, on_done=None, accept=None):
    """kind(1つ・複数どちらでも)に runner を結び付ける。同じ kind を2回登録すると後勝ち。
    accept を渡すと /api/inquiry(裸パス)からその kind に来たリクエストもこの関数が受ける。"""
    if isinstance(kinds, str):
        kinds = (kinds,)
    for k in kinds:
        _RUNNERS[k] = runner
        _ON_DONE[k] = on_done
        if accept is not None:
            _ACCEPT[k] = accept


def register_default_accept(fn):
    """rewrite/fix・room 固有の kind 一覧のどれでもない kind(add/ask を含む。旧 api_inquiry の
    最後の else 分岐)を受ける既定ハンドラを1つ登録する(docs room)。"""
    _DEFAULT_ACCEPT[0] = fn


def new_id():
    return time.strftime("%Y%m%d-%H%M%S", time.localtime()) + "-" + uuid.uuid4().hex[:4]


def _persist(job):
    """1行 append。同じ id の行が複数あっても最後の行を正とする(読み込み側が上書きしながら読む)"""
    rec = dict(job)
    if rec.get("text") and len(rec["text"]) > 300:
        rec["text"] = rec["text"][:300] + "…"
    try:
        os.makedirs(os.path.dirname(JOBS_LOG), exist_ok=True)
        with open(JOBS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _load():
    out = {}
    try:
        with open(JOBS_LOG, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    j = json.loads(line)
                except Exception:
                    continue
                if j.get("id"):
                    out[j["id"]] = j
    except OSError:
        pass
    return out


JOBS = _load()   # 再起動しても過去のジョブ結果を GET /api/inquiry/<job> で引ける


def create(kind, text, timeout, extra=None):
    job = {"id": new_id(), "kind": kind, "text": text, "status": "queued",
           "created": collect.now().isoformat(timespec="seconds"), "timeout": timeout}
    if extra:
        job.update(extra)
    with JOBS_LOCK:
        JOBS[job["id"]] = job
    _persist(job)
    _QUEUE.put(job["id"])
    return job


def get(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        return dict(job) if job else None


def recent(kind, n=3):
    with JOBS_LOCK:
        items = [dict(j) for j in JOBS.values() if j.get("kind") == kind and j.get("status") == "done"]
    items.sort(key=lambda j: j.get("finished") or j.get("created") or "", reverse=True)
    return items[:n]


def _process(job_id):
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        job["status"] = "running"
        kind = job["kind"]
        job_snapshot = dict(job)
    runner = _RUNNERS.get(kind)
    if runner is None:
        res = {"ok": False, "error": f"unknown job kind: {kind}"}
    else:
        res = runner(job_snapshot)
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if not job:
            return
        result = {k: v for k, v in res.items() if k != "ok"}
        job["result"] = result
        if res.get("ok") and res.get("done"):
            job["status"] = "done"
        else:
            job["status"] = "failed"
            job["error"] = res.get("error") or "処理がタイムアウトまたは失敗しました"
        job["finished"] = collect.now().isoformat(timespec="seconds")
        job_copy = dict(job)
    _persist(job_copy)
    on_done = _ON_DONE.get(job_copy.get("kind"))
    if on_done:
        try:
            on_done(job_copy)
        except Exception:
            pass


def worker():
    """1本のワーカーだけが処理するので、登録された全 kind のジョブが順番に処理される
    (docs スレの tmux 送信など、同じ外部リソースに複数の kind が同時に触らないように、意図して直列)。"""
    while True:
        job_id = _QUEUE.get()
        try:
            _process(job_id)
        except Exception as e:
            with JOBS_LOCK:
                job = JOBS.get(job_id)
                if job:
                    job["status"] = "failed"
                    job["error"] = str(e)
                    job["finished"] = collect.now().isoformat(timespec="seconds")
                    job_copy = dict(job)
                else:
                    job_copy = None
            if job_copy:
                _persist(job_copy)
        finally:
            _QUEUE.task_done()


INQUIRY_HELP = "kind(add|ask|rewrite|fix) と text(add/ask/fix) または path(rewrite/fix) を JSON で POST してください(例: {\"kind\":\"add\",\"text\":\"...\"})"
PHOTO_EXT = {".jpg", ".jpeg", ".png", ".webp"}
MAX_PHOTOS = 10


def validate_photos(photos, inbox_dir):
    """/api/upload が返したパス(inboxのファイル名 or フルパス)を検証する。inbox 配下・許可拡張子・
    存在するものだけ、最大 MAX_PHOTOS 件(旧 core/server.py・docs room の _validate_photos と同一)。"""
    out = []
    for p in photos or []:
        base = os.path.basename(str(p or "").strip())
        if not base:
            continue
        ext = os.path.splitext(base)[1].lower()
        if ext not in PHOTO_EXT:
            continue
        real = os.path.join(inbox_dir, base)
        if not os.path.isfile(real):
            continue
        if real not in out:
            out.append(real)
        if len(out) >= MAX_PHOTOS:
            break
    return out


def normalize_inquiry_body(body):
    """ショートカット由来のゆるい本文を {kind, text, path, photos, sync, timeout} に揃える。
    (1) キー名は大文字小文字を無視 (2) kind/text が無く、値が辞書のキーが1つだけなら中身を使う(空キー含む)
    (3) kind が無ければ add (4) text は前後の空白・改行を trim(旧 core/server.py・docs room と同一)"""
    import json as _json
    import re as _re
    if not isinstance(body, dict):
        return {}

    def lower_keys(d):
        return {str(k).strip().lower(): v for k, v in d.items()}

    def as_dict(v):
        if isinstance(v, str) and v.lstrip().startswith("{"):
            try:
                v = _json.loads(v)
            except Exception:
                return None
        return v if isinstance(v, dict) else None

    def as_list(v):
        if isinstance(v, list):
            out = []
            for x in v:
                out += as_list(x)
            return out
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                try:
                    j = _json.loads(s)
                    if isinstance(j, list):
                        return as_list(j)
                except Exception:
                    pass
            parts = [x.strip() for x in _re.split(r"[\n,]", s) if x.strip()]
            if len(parts) > 1:
                return parts
            if s:
                return [s]
        return []

    b = lower_keys(body)
    for _ in range(2):   # 二重構造の展開は2段まで
        if "text" in b or "kind" in b:
            break
        dict_vals = [d for d in (as_dict(v) for v in b.values()) if d is not None]
        if len(dict_vals) == 1 and (len(b) == 1 or "text" in lower_keys(dict_vals[0])):
            b = lower_keys(dict_vals[0])
        else:
            break
    out = dict(b)
    out["kind"] = str(b.get("kind") or "add").strip().lower()
    out["text"] = str(b.get("text") or "").strip()
    out["path"] = str(b.get("path") or "").strip()
    photos = []
    for k in ("photos", "photo", "photopath", "photopaths", "images", "image", "files"):
        photos += as_list(b.get(k))
    out["photos"] = [p for p in photos if p]
    return out


def api_inquiry(body):
    """POST /api/inquiry(裸パス)本体。kind から room が登録した accept を引いて呼ぶだけ
    (rewrite/fix・room 固有の kind 一覧はそれぞれの room が register() の accept= で登録済み。
    どれにも当たらなければ register_default_accept() の既定ハンドラ=docs room に回す)。"""
    body = normalize_inquiry_body(body)
    kind = body.get("kind", "add")
    accept = _ACCEPT.get(kind) or _DEFAULT_ACCEPT[0]
    if accept is None:
        return {"ok": False, "error": f"kind が '{kind}' です。" + INQUIRY_HELP}
    return accept(body)


def access_log(handler, status, ct="", blen=0, kind="", text="", note="", raw=b""):
    """/api/inquiry* への全リクエストを1行ずつ記録(ショートカットからの送信が届いたかの切り分け用)"""
    try:
        os.makedirs(C.LOG_DIR, exist_ok=True)
        ip = handler.headers.get("X-Forwarded-For", "") or (handler.client_address[0] if handler.client_address else "")
        rec = {"ts": collect.now().isoformat(timespec="seconds"), "method": handler.command,
               "path": handler.path[:200], "ip": ip.split(",")[0].strip(), "content_type": (ct or "")[:80],
               "body_len": int(blen or 0), "kind": kind, "text_head": (text or "")[:40], "status": int(status),
               "note": note, "ua": (handler.headers.get("User-Agent", "") or "")[:80]}
        if int(status) >= 400 and raw:
            rec["raw_head"] = raw[:900].decode("utf-8", "replace")[:300]   # 400 のときだけ生の本文(先頭300字)を残す
        with open(ACCESS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass
