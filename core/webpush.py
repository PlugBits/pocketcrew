#!/usr/bin/env python3
"""Web Push(VAPID + aes128gcm, RFC 8291/8292)の最小実装。依存は cryptography のみ。
購読情報と VAPID 鍵は push.json(リポジトリ直下) に保存する。"""
import os, sys, json, time, base64, struct, urllib.request, urllib.error
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

# core/webpush.py が単体で読み込まれても "core" パッケージが見えるように、
# リポジトリ直下(このファイルの2つ上)を sys.path に足す
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import config as C

STORE = C.PUSH_STORE
SUBJECT = C.PUSH_SUBJECT   # Apple は mailto の不正なドメイン(localhost)を BadJwtToken で拒む


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def b64u_dec(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _load():
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"vapid": None, "subs": []}


def _save(d):
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.chmod(tmp, 0o600)
    os.replace(tmp, STORE)


def vapid_keys():
    """VAPID 鍵(初回に生成)。戻り値は (private_key, public_key_b64url)"""
    d = _load()
    if not d.get("vapid"):
        k = ec.generate_private_key(ec.SECP256R1())
        pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
        pub = k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        d["vapid"] = {"private_pem": pem, "public_b64": b64u(pub)}
        _save(d)
    k = serialization.load_pem_private_key(d["vapid"]["private_pem"].encode(), password=None)
    return k, d["vapid"]["public_b64"]


def public_key() -> str:
    return vapid_keys()[1]


def subscribe(sub: dict):
    if not sub or not sub.get("endpoint") or not sub.get("keys"):
        return {"ok": False, "error": "bad subscription"}
    d = _load()
    d["subs"] = [s for s in d["subs"] if s["endpoint"] != sub["endpoint"]] + [
        {"endpoint": sub["endpoint"], "keys": {"p256dh": sub["keys"]["p256dh"], "auth": sub["keys"]["auth"]},
         "added": int(time.time()), "ua": sub.get("ua", "")}]
    _save(d)
    return {"ok": True, "count": len(d["subs"])}


def unsubscribe(endpoint: str):
    d = _load()
    d["subs"] = [s for s in d["subs"] if s["endpoint"] != endpoint]
    _save(d)
    return {"ok": True, "count": len(d["subs"])}


def subscriptions():
    return _load()["subs"]


def get_level():
    return _load().get("level", "done")


def set_level(level: str):
    if level not in ("need", "done", "all"):
        return {"ok": False, "error": "bad level"}
    d = _load(); d["level"] = level; _save(d)
    return {"ok": True, "level": level}


def _vapid_jwt(endpoint: str) -> str:
    from urllib.parse import urlparse
    u = urlparse(endpoint)
    k, _ = vapid_keys()
    header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": SUBJECT}).encode())
    signing = f"{header}.{claims}".encode()
    der = k.sign(signing, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return f"{header}.{claims}." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


def _encrypt(payload: bytes, p256dh: str, auth: str) -> bytes:
    """RFC 8291 aes128gcm。戻り値は本文(salt | rs | idlen | as_public | ciphertext)"""
    ua_pub_raw = b64u_dec(p256dh)
    auth_secret = b64u_dec(auth)
    ua_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub_raw)
    as_priv = ec.generate_private_key(ec.SECP256R1())
    as_pub_raw = as_priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    shared = as_priv.exchange(ec.ECDH(), ua_pub)
    ikm = HKDF(hashes.SHA256(), 32, auth_secret, b"WebPush: info\x00" + ua_pub_raw + as_pub_raw).derive(shared)
    salt = os.urandom(16)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    ct = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)   # 0x02 = 最終レコードの区切り
    return salt + struct.pack(">I", 4096) + bytes([len(as_pub_raw)]) + as_pub_raw + ct


def send(sub: dict, data: dict, ttl: int = 600, urgency: str = "high"):
    """1件送信。戻り値 (status, detail)。410/404 なら購読切れ"""
    body = _encrypt(json.dumps(data, ensure_ascii=False).encode(), sub["keys"]["p256dh"], sub["keys"]["auth"])
    req = urllib.request.Request(sub["endpoint"], data=body, method="POST", headers={
        "Content-Type": "application/octet-stream",
        "Content-Encoding": "aes128gcm",
        "TTL": str(ttl),
        "Urgency": urgency,
        "Authorization": f"vapid t={_vapid_jwt(sub['endpoint'])}, k={public_key()}",
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200].decode(errors="replace")
    except Exception as e:
        return 0, str(e)


def broadcast(title: str, body: str = "", url: str = "/", tag: str = ""):
    """全購読へ送る。切れた購読は掃除する"""
    d = _load()
    results, alive = [], []
    for s in d["subs"]:
        status, detail = send(s, {"title": title, "body": body, "url": url, "tag": tag or title})
        results.append({"endpoint": s["endpoint"][-24:], "status": status, "detail": detail})
        if status not in (404, 410):
            alive.append(s)
    if len(alive) != len(d["subs"]):
        d["subs"] = alive
        _save(d)
    return results


if __name__ == "__main__":
    import sys
    print("public key:", public_key())
    print("subs:", len(subscriptions()))
    if len(sys.argv) > 1:
        print(broadcast("ポケクル", " ".join(sys.argv[1:])))
