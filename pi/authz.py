#!/usr/bin/env python3
"""
遠隔施解錠の認可モジュール（document/REMOTE_UNLOCK_DESIGN.md §4〜§6 の実装）。

- authz.json（ユーザー公開鍵と権限表）を読み、更新を検知して自動で再読込する
- コマンドの Ed25519 署名を検証し、ユーザーを特定する
- 時刻窓 + nonce（SQLite に 24 時間保存）で再送を防ぐ
- grant（錠 × 操作 × 期間 × 時間帯）とレート制限を判定する
- authz.json が読めない／壊れているときは全拒否（フェイルクローズ）

依存: pycryptodome（Ed25519 は Crypto.Signature.eddsa）
"""
from __future__ import annotations

import base64
import collections
import datetime as dt
import json
import logging
import os
import sqlite3
import threading
import time
from zoneinfo import ZoneInfo

from Crypto.PublicKey import ECC
from Crypto.Signature import eddsa

log = logging.getLogger("authz")

ACTIONS = ("lock", "unlock")
DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
SIGNED_FIELDS = ("v", "req_id", "user", "lock", "action", "ts", "nonce")


class Denied(Exception):
    """認可失敗。code は結果 payload の code にそのまま使う。"""

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


# ---- 署名 ---------------------------------------------------------------
def canonical_bytes(cmd: dict) -> bytes:
    """署名対象: sig を除いたフィールドをキー順・空白なしの JSON にした UTF-8。"""
    body = {k: cmd[k] for k in SIGNED_FIELDS if k in cmd}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# Ed25519 公開鍵の SubjectPublicKeyInfo(DER) 固定ヘッダ（RFC 8410）。pycryptodome は raw 32B を直接 import できないため。
_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def load_public_key(b64: str):
    raw = base64.b64decode(b64)
    if len(raw) != 32:
        raise ValueError("Ed25519 公開鍵は 32 バイト")
    return ECC.import_key(_ED25519_SPKI_PREFIX + raw)


def sign(cmd: dict, private_key) -> str:
    return base64.b64encode(eddsa.new(private_key, "rfc8032").sign(canonical_bytes(cmd))).decode()


def verify(cmd: dict, public_key) -> bool:
    try:
        eddsa.new(public_key, "rfc8032").verify(canonical_bytes(cmd), base64.b64decode(cmd["sig"]))
        return True
    except (ValueError, KeyError, TypeError):
        return False


def generate_keypair():
    """(private_key_pem, public_key_b64)"""
    key = ECC.generate(curve="Ed25519")
    return key.export_key(format="PEM"), base64.b64encode(key.public_key().export_key(format="raw")).decode()


# ---- nonce ストア -----------------------------------------------------------
class NonceStore:
    def __init__(self, path: str, keep_sec: int = 86400):
        self.keep = keep_sec
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS nonces (nonce TEXT PRIMARY KEY, ts INTEGER)")
        self.db.commit()

    def check_and_add(self, nonce: str, now: int) -> bool:
        """未使用なら登録して True。使用済みなら False。"""
        with self.lock:
            self.db.execute("DELETE FROM nonces WHERE ts < ?", (now - self.keep,))
            try:
                self.db.execute("INSERT INTO nonces VALUES (?, ?)", (nonce, now))
                self.db.commit()
                return True
            except sqlite3.IntegrityError:
                return False


# ---- レート制限 -----------------------------------------------------------
class RateLimiter:
    def __init__(self):
        self.hits = collections.defaultdict(collections.deque)
        self.lock = threading.Lock()

    def check(self, key: str, limit: int, window_sec: int, now: float) -> bool:
        with self.lock:
            q = self.hits[key]
            while q and q[0] <= now - window_sec:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True


# ---- 認可本体 --------------------------------------------------------------
class Authz:
    def __init__(self, path: str, nonce_db: str | None = None):
        self.path = path
        self.cfg = None            # None = 読めていない（全拒否）
        self.mtime = None
        self.users = {}            # user_id -> (dict, public_key)
        self.nonces = NonceStore(nonce_db or os.path.join(os.path.dirname(os.path.abspath(path)), "nonces.db"))
        self.rate = RateLimiter()
        self.reload()

    # -- 読込 --
    def reload(self) -> bool:
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            if self.cfg is not None or self.mtime is None:
                log.error("authz.json がありません: %s（全コマンド拒否）", self.path)
            self.cfg, self.mtime, self.users = None, 0, {}
            return False
        if st.st_mtime == self.mtime:
            return False
        try:
            with open(self.path, encoding="utf-8") as f:
                cfg = json.load(f)
            users = {}
            for uid, u in cfg.get("users", {}).items():
                users[uid] = (u, load_public_key(u["pubkey"]))
            self.cfg, self.users, self.mtime = cfg, users, st.st_mtime
            log.info("authz.json 読込: users=%d enabled=%s allowed_actions=%s",
                     len(users), cfg.get("enabled", False), cfg.get("allowed_actions", ["lock"]))
            return True
        except Exception as e:  # noqa: BLE001
            log.error("authz.json が不正です: %s（全コマンド拒否）", e)
            self.cfg, self.users, self.mtime = None, st.st_mtime, {}
            return False

    def maybe_reload(self):
        try:
            if os.stat(self.path).st_mtime != self.mtime:
                self.reload()
        except FileNotFoundError:
            if self.cfg is not None:
                self.reload()

    @property
    def enabled(self) -> bool:
        return bool(self.cfg and self.cfg.get("enabled"))

    @property
    def allowed_actions(self) -> list:
        return list(self.cfg.get("allowed_actions", ["lock"])) if self.cfg else []

    def summary(self) -> dict:
        return {"enabled": self.enabled, "users": len(self.users), "allowed_actions": self.allowed_actions}

    # -- 判定 --
    def authorize(self, topic_lock: str, cmd: dict, now: float | None = None) -> dict:
        """設計書 §4.2 の順序で判定する。通れば user dict を返し、拒否なら Denied。"""
        now = time.time() if now is None else now
        self.maybe_reload()
        if not self.enabled:
            raise Denied("DISABLED", "遠隔操作は無効です")
        # 形式
        for k in ("v", "req_id", "user", "lock", "action", "ts", "nonce", "sig"):
            if k not in cmd:
                raise Denied("BAD_REQUEST", f"{k} がありません")
        if cmd["v"] != 1:
            raise Denied("BAD_REQUEST", "未対応のバージョン")
        if cmd["lock"] != topic_lock:
            raise Denied("BAD_REQUEST", "lock がトピックと一致しません")
        if cmd["action"] not in ACTIONS:
            raise Denied("BAD_REQUEST", "未知の action")
        # 署名 → 送信者特定
        entry = self.users.get(str(cmd["user"]))
        if entry is None:
            raise Denied("BAD_SIG", "署名を検証できません")       # ユーザーの存在を漏らさない
        user, pub = entry
        if not verify(cmd, pub):
            raise Denied("BAD_SIG", "署名を検証できません")
        if not user.get("enabled", False):
            raise Denied("FORBIDDEN", "ユーザーは無効です")
        # 時刻窓 + nonce
        skew = int(self.cfg.get("clock_skew_sec", 60))
        try:
            ts = int(cmd["ts"])
        except (TypeError, ValueError):
            raise Denied("BAD_REQUEST", "ts が不正")
        if abs(ts - now) > skew:
            raise Denied("EXPIRED", f"時刻のずれが {skew} 秒を超えています")
        nonce = str(cmd["nonce"])
        if not (8 <= len(nonce) <= 64):
            raise Denied("BAD_REQUEST", "nonce の長さが不正")
        if not self.nonces.check_and_add(nonce, int(now)):
            raise Denied("REPLAY", "使用済みの nonce")
        # 全体で許可された操作か（フェーズ制御）
        if cmd["action"] not in self.allowed_actions:
            raise Denied("FORBIDDEN", f"{cmd['action']} は現在許可されていません")
        # grant
        if not any(self._grant_matches(g, cmd["lock"], cmd["action"], now) for g in user.get("grants", [])):
            raise Denied("FORBIDDEN", "この錠・操作の権限がありません")
        # レート制限
        limits = self.cfg.get("limits", {})
        if cmd["action"] == "unlock":
            per_min = int(limits.get("unlock_per_minute", 3))
            per_hour = int(limits.get("unlock_per_hour", 20))
            if not self.rate.check(f"u:{cmd['user']}:m", per_min, 60, now) or \
               not self.rate.check(f"l:{cmd['lock']}:m", per_min, 60, now):
                raise Denied("RATE_LIMIT", "解錠回数が多すぎます（毎分）")
            if not self.rate.check(f"u:{cmd['user']}:h", per_hour, 3600, now) or \
               not self.rate.check(f"l:{cmd['lock']}:h", per_hour, 3600, now):
                raise Denied("RATE_LIMIT", "解錠回数が多すぎます（毎時）")
        else:
            per_min = int(limits.get("lock_per_minute", 10))
            if not self.rate.check(f"u:{cmd['user']}:lm", per_min, 60, now):
                raise Denied("RATE_LIMIT", "施錠回数が多すぎます")
        return user

    def _grant_matches(self, g: dict, lock: str, action: str, now: float) -> bool:
        if lock not in g.get("locks", []) or action not in g.get("actions", []):
            return False
        tz = ZoneInfo(g.get("tz") or (self.cfg.get("tz") if self.cfg else None) or "Asia/Tokyo")
        t = dt.datetime.fromtimestamp(now, tz)
        if g.get("valid_from") and t < dt.datetime.fromisoformat(g["valid_from"]).astimezone(tz):
            return False
        if g.get("valid_until") and t > dt.datetime.fromisoformat(g["valid_until"]).astimezone(tz):
            return False
        sched = g.get("schedule")
        if sched:
            if sched.get("days") and DAY_NAMES[t.weekday()] not in sched["days"]:
                return False
            if sched.get("hours"):
                hm = t.hour * 60 + t.minute
                ok = False
                for rng in sched["hours"]:
                    a, b = rng.split("-")
                    ah, am = map(int, a.split(":"))
                    bh, bm = map(int, b.split(":"))
                    if ah * 60 + am <= hm < bh * 60 + bm:
                        ok = True
                        break
                if not ok:
                    return False
        return True
