#!/usr/bin/env python3
"""
MQTT 経由の遠隔施解錠（document/REMOTE_UNLOCK_DESIGN.md §5〜§7 の実装）。
ブリッジ（sesame_mqtt_bridge.py）から使う。

- `<p>/<alias>/cmd` を購読し、authz.Authz で認可してから、ブリッジが保持している BLE セッションでコマンドを送る
- 結果を `<p>/<alias>/cmd/result/<req_id>` に返す
- すべてのコマンドを audit.log（JSON Lines）に記録する
- 有効化条件: authz.json が存在し、かつ MQTT が認証付き（username あり）か --simulate のとき
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import time

from authz import Authz, Denied
from sesame_protocol import (
    CMD_CHAR_UUID, ITEM_LOCK, ITEM_MECH_STATUS, ITEM_UNLOCK, OP_PUBLISH, OP_RESPONSE,
    SEG_ENCRYPTED, parse_mech_status,
)

log = logging.getLogger("remote")
ITEM_BY_ACTION = {"lock": ITEM_LOCK, "unlock": ITEM_UNLOCK}
EXPECT_STATE = {"lock": "LOCKED", "unlock": "UNLOCKED"}
SIM_STATUS = {"LOCKED": "fb0b0080030012", "UNLOCKED": "fb0b0080a4ff54"}


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def history_tag(text: str) -> bytes:
    raw = (text or "MQTT").encode("utf-8")[:20]
    return bytes([len(raw)]) + raw


# ---- BLE セッションへの橋渡し -------------------------------------------------
class LiveLink:
    """ブリッジが持つ 1 本の BLE 接続に対して、コマンド送信と応答待ちを行う。"""

    def __init__(self, client, sess):
        self.client = client
        self.sess = sess
        self.responses: asyncio.Queue = asyncio.Queue()
        self.statuses: asyncio.Queue = asyncio.Queue()
        self.busy = asyncio.Lock()

    def feed(self, op: int, item: int, payload: bytes):
        """ブリッジの通知ハンドラから呼ぶ（asyncio ループ内）。"""
        if op == OP_RESPONSE and item in (ITEM_LOCK, ITEM_UNLOCK):
            self.responses.put_nowait((item, payload[0] if payload else None))
        elif op == OP_PUBLISH and item == ITEM_MECH_STATUS and self.sess.mech_status:
            self.statuses.put_nowait(dict(self.sess.mech_status))

    async def send(self, action: str, tag: str, timeout: float = 8.0) -> dict:
        async with self.busy:
            # 古い残骸を捨てる
            for q in (self.responses, self.statuses):
                while not q.empty():
                    q.get_nowait()
            before = self.sess.mech_status["state"] if self.sess.mech_status else None
            packet = bytes([SEG_ENCRYPTED]) + self.sess.encrypt(bytes([ITEM_BY_ACTION[action]]) + history_tag(tag))
            t0 = time.monotonic()
            await self.client.write_gatt_char(CMD_CHAR_UUID, packet, response=False)
            res = {"state_before": before, "response": None, "state_after": None}
            try:
                _, code = await asyncio.wait_for(self.responses.get(), timeout=timeout)
                res["response"] = code
            except asyncio.TimeoutError:
                pass
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                try:
                    st = await asyncio.wait_for(self.statuses.get(), timeout=max(0.1, deadline - time.monotonic()))
                except asyncio.TimeoutError:
                    break
                res["state_after"] = st["state"]
                if st["state"] == EXPECT_STATE[action]:
                    break
            res["elapsed_sec"] = round(time.monotonic() - t0, 2)
            return res


class SimLink:
    """--simulate 用。BLE なしで状態変化を偽装する。"""

    def __init__(self, tracker):
        self.tracker = tracker

    async def send(self, action: str, tag: str, timeout: float = 8.0) -> dict:
        before = self.tracker.last_status["state"] if self.tracker.last_status else None
        await asyncio.sleep(0.3)
        st = parse_mech_status(bytes.fromhex(SIM_STATUS[EXPECT_STATE[action]]))
        self.tracker.on_mech_status(st)
        return {"state_before": before, "response": 0, "state_after": st["state"], "elapsed_sec": 0.3}


# ---- 遠隔操作本体 --------------------------------------------------------------
class RemoteControl:
    def __init__(self, cfg: dict, cfg_dir: str, pub, trackers: list, simulate: bool):
        rc = cfg.get("remote_control", {})
        self.pub = pub
        self.trackers = {t.alias: t for t in trackers}
        self.simulate = simulate
        self.authz_path = os.path.join(cfg_dir, rc.get("authz_file", "authz.json"))
        self.audit_path = os.path.join(cfg_dir, rc.get("audit_log", "audit.log"))
        self.cmd_timeout = float(rc.get("cmd_timeout_sec", 8))
        self.queue: asyncio.Queue = asyncio.Queue()
        self.results = {}            # req_id -> (ts, result) 冪等性
        self.authz = None
        self.reason = None           # 無効な理由（None なら有効）

        auth_broker = bool(cfg["mqtt"].get("username"))
        if not os.path.exists(self.authz_path):
            self.reason = "authz.json がない"
        elif not auth_broker and not simulate:
            self.reason = "公開ブローカー（認証なし）のため無効"
        if self.reason is None:
            self.authz = Authz(self.authz_path)

    @property
    def active(self) -> bool:
        return self.reason is None

    def summary(self) -> dict:
        s = {"remote_control": "active" if self.active else f"disabled: {self.reason}", "ts": now_iso()}
        if self.authz:
            s.update(self.authz.summary())
        return s

    def start(self):
        self.pub.publish("bridge/authz", self.summary(), retain=True)
        if not self.active:
            log.warning("遠隔操作は無効: %s", self.reason)
            return
        for alias in self.trackers:
            self.pub.subscribe(self.pub.topic(f"{alias}/cmd"), self._on_mqtt)
        log.info("遠隔操作を有効化: %s", self.authz.summary())

    # paho のスレッドから呼ばれる
    def _on_mqtt(self, client, userdata, msg):
        alias = msg.topic[len(self.pub.prefix) + 1:].split("/")[0]
        try:
            cmd = json.loads(msg.payload.decode("utf-8"))
            assert isinstance(cmd, dict)
        except Exception:  # noqa: BLE001
            self.audit({"alias": alias, "ok": False, "code": "BAD_REQUEST", "message": "JSON ではない"})
            return
        self.loop.call_soon_threadsafe(self.queue.put_nowait, (alias, cmd))

    async def worker(self, stop: asyncio.Event):
        self.loop = asyncio.get_running_loop()
        while not stop.is_set():
            getter = asyncio.create_task(self.queue.get())
            stopper = asyncio.create_task(stop.wait())
            done, _ = await asyncio.wait({getter, stopper}, return_when=asyncio.FIRST_COMPLETED)
            stopper.cancel()
            if getter not in done:
                getter.cancel()
                break
            alias, cmd = getter.result()
            try:
                await self.handle(alias, cmd)
            except Exception as e:  # noqa: BLE001
                log.exception("コマンド処理で例外: %s", e)

    async def handle(self, alias: str, cmd: dict):
        req_id = str(cmd.get("req_id", ""))[:64]
        user_id = str(cmd.get("user", ""))[:64]
        action = str(cmd.get("action", ""))[:16]
        base = {"req_id": req_id, "user": user_id, "lock": alias, "action": action, "ts": now_iso()}

        # 冪等性: 同じ req_id は前回の結果を返す
        self._purge_results()
        if req_id in self.results:
            self.pub.publish(f"{alias}/cmd/result/{req_id}", self.results[req_id][1])
            return

        try:
            if self.authz is None:
                raise Denied("DISABLED", self.reason or "無効")
            user = self.authz.authorize(alias, cmd)
            tr = self.trackers.get(alias)
            if tr is None:
                raise Denied("BAD_REQUEST", "未知の錠")
            link = SimLink(tr) if self.simulate else tr.link
            if link is None:
                raise Denied("BLE_OFFLINE", "錠に BLE 接続していません")
            tr.note_command(user_id, action)
            res = await link.send(action, user.get("history_tag", f"MQTT:{user_id}"), self.cmd_timeout)
            ok = res.get("response") == 0 and res.get("state_after") == EXPECT_STATE[action]
            result = {**base, "ok": ok, **res}
            if not ok:
                result["code"] = "TIMEOUT" if res.get("response") == 0 else "DEVICE_ERROR"
                result["message"] = "コマンドは送信済みですが、期待した状態を確認できませんでした" \
                    if res.get("response") == 0 else f"デバイスが拒否しました（res={res.get('response')}）"
        except Denied as d:
            result = {**base, "ok": False, "code": d.code, "message": str(d)}
        except Exception as e:  # noqa: BLE001
            result = {**base, "ok": False, "code": "ERROR", "message": str(e)}

        self.audit(result)
        if req_id:
            self.results[req_id] = (time.time(), result)
            self.pub.publish(f"{alias}/cmd/result/{req_id}", result)
        (log.info if result["ok"] else log.warning)("[%s] %s by %s → %s %s", alias, action, user_id,
                                                      "OK" if result["ok"] else result.get("code"),
                                                      result.get("message", ""))

    def _purge_results(self, keep_sec=600):
        cutoff = time.time() - keep_sec
        for k in [k for k, (t, _) in self.results.items() if t < cutoff]:
            del self.results[k]

    def audit(self, record: dict):
        try:
            with open(self.audit_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": now_iso(), **record}, ensure_ascii=False) + "\n")
        except OSError as e:
            log.error("監査ログに書けません: %s", e)
