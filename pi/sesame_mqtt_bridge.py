#!/usr/bin/env python3
"""
Sesame 5 → MQTT ブリッジ（Raspberry Pi 常駐サービス）。

Sesame 5 に BLE で接続してログインし、施錠/解錠のたびに届く mechStatus 通知を
MQTT に publish する。設計は document/MQTT_BRIDGE_DESIGN.md を参照。

依存: pip install bleak pycryptodome paho-mqtt

使い方:
  python3 sesame_mqtt_bridge.py -c config.json
  python3 sesame_mqtt_bridge.py -c config.json --simulate   # BLE を使わず擬似状態を流す（MQTT 経路の確認用）

トピック（<p> = mqtt.topic_prefix, <a> = devices[].alias）:
  <p>/bridge/availability   online|offline            retained（LWT）
  <p>/bridge/heartbeat      JSON                      retained、60 秒ごと
  <p>/<a>/availability      online|offline            retained（BLE 接続状態）
  <p>/<a>/status            JSON（現在状態）           retained、状態通知のたび + 定期再送
  <p>/<a>/setting           JSON（施錠/解錠位置など）   retained
  <p>/<a>/event             JSON（locked|unlocked）    非 retained、状態が変わったときだけ（遠隔操作なら by=ユーザー）
  <p>/<a>/cmd               JSON（署名付きコマンド）    アプリ → ブリッジ。remote_control.py / authz.py 参照
  <p>/<a>/cmd/result/<id>   JSON（実行結果）           ブリッジ → アプリ
  <p>/bridge/authz          JSON                      retained、遠隔操作の有効状態（秘密を含まない）
"""
import argparse
import asyncio
import datetime as dt
import json
import logging
import random
import signal
import ssl
import sys
import time

import paho.mqtt.client as mqtt

from remote_control import LiveLink, RemoteControl
from sesame_protocol import (
    CMD_CHAR_UUID, ITEM_INITIAL, ITEM_MECH_STATUS, OP_PUBLISH, STATUS_CHAR_UUID,
    BleakClient, BleakScanner, SesameSession, format_status, parse_mech_status,
)

log = logging.getLogger("bridge")
STABLE_STATES = ("LOCKED", "UNLOCKED")


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ---- MQTT ------------------------------------------------------------------
class MqttPublisher:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.prefix = cfg["topic_prefix"].rstrip("/")
        self.qos = int(cfg.get("qos", 1))
        self.connected = False
        self._retained = {}      # topic -> payload。再接続時に再送して retained 状態を復元する
        self._pending = []       # 未接続中に発生した非 retained メッセージ（イベント）。接続後に送る
        self._pending_max = 200
        self._subs = []          # (topic, handler) 再接続時に購読し直す
        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=cfg.get("client_id") or f"sesame-bridge-{random.randrange(1 << 24):06x}",
            protocol=mqtt.MQTTv311,
            clean_session=True,
        )
        if cfg.get("username"):
            self.client.username_pw_set(cfg["username"], cfg.get("password"))
        if cfg.get("tls", True):
            self.client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        self.client.will_set(self.topic("bridge/availability"), "offline", qos=self.qos, retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.reconnect_delay_set(min_delay=2, max_delay=60)

    def topic(self, suffix: str) -> str:
        return f"{self.prefix}/{suffix}"

    def start(self):
        log.info("MQTT 接続中: %s:%s tls=%s prefix=%s", self.cfg["host"], self.cfg["port"],
                 self.cfg.get("tls", True), self.prefix)
        self.client.connect_async(self.cfg["host"], int(self.cfg["port"]), keepalive=60)
        self.client.loop_start()

    def stop(self):
        try:
            self.publish("bridge/availability", "offline", retain=True)
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self.connected = True
            log.info("MQTT 接続完了")
            self.publish("bridge/availability", "online", retain=True)
            # 切断中に溜まった状態・イベントを流す
            for topic, payload in list(self._retained.items()):
                self.client.publish(topic, payload, qos=self.qos, retain=True)
            pending, self._pending = self._pending, []
            for topic, payload in pending:
                self.client.publish(topic, payload, qos=self.qos, retain=False)
            if pending:
                log.info("切断中のイベント %d 件を送信", len(pending))
            for topic, _ in self._subs:
                self.client.subscribe(topic, qos=self.qos)
        else:
            log.error("MQTT 接続失敗: %s", reason_code)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        log.warning("MQTT 切断: %s（自動再接続します）", reason_code)

    def subscribe(self, topic: str, handler):
        """topic への購読を登録する。handler(client, userdata, msg) は paho のスレッドで呼ばれる。"""
        self._subs.append((topic, handler))
        self.client.message_callback_add(topic, handler)
        if self.connected:
            self.client.subscribe(topic, qos=self.qos)

    def publish(self, suffix: str, payload, retain=False):
        if not isinstance(payload, str):
            payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        topic = self.topic(suffix)
        if retain:
            self._retained[topic] = payload
        if not self.connected:
            if not retain:
                self._pending.append((topic, payload))
                del self._pending[:-self._pending_max]
            log.debug("MQTT 未接続のため保留: %s", suffix)
            return
        info = self.client.publish(topic, payload, qos=self.qos, retain=retain)
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            log.warning("publish 失敗 rc=%s topic=%s", info.rc, suffix)
            if not retain:
                self._pending.append((topic, payload))
        else:
            log.debug("publish %s %s", suffix, payload)


# ---- デバイス 1 台分の状態追跡 ----------------------------------------------
class DeviceTracker:
    def __init__(self, dev_cfg: dict, pub: MqttPublisher):
        self.alias = dev_cfg["alias"]
        self.name = dev_cfg.get("name") or None   # アプリで付けた名前（config.json の name。未設定なら null）
        self.mac = dev_cfg["mac"].upper()
        self.secret = dev_cfg["secret"]
        self.pub = pub
        self.last_status = None          # 最後に受け取った mechStatus（dict）
        self.last_stable_state = None    # 最後に確定した LOCKED / UNLOCKED
        self.last_change_ts = None
        self.seq = 0
        self.connected = False
        self.link = None                 # 接続中の BLE セッション（remote_control.LiveLink）
        self.last_cmd = None             # (user, action, monotonic) 直近の遠隔コマンド。event.by に使う

    def status_payload(self, st: dict) -> dict:
        return {
            "alias": self.alias,
            "name": self.name,
            "state": st["state"],
            "locked": st["state"] == "LOCKED",
            "battery_pct": st["battery_pct"],
            "voltage": st["voltage"],
            "battery_critical": st["battery_critical"],
            "position": st["position"],
            "target": st["target"],
            "flags": st["flags"],
            "last_change_ts": self.last_change_ts,
            "ts": now_iso(),
            "seq": self.seq,
        }

    def on_mech_status(self, st: dict):
        self.seq += 1
        self.last_status = st
        state = st["state"]
        log.info("[%s] %s", self.alias, format_status(st))

        if state in STABLE_STATES and state != self.last_stable_state:
            prev = self.last_stable_state
            self.last_stable_state = state
            self.last_change_ts = now_iso()
            if prev is not None:   # 起動直後の初回は「変化」ではないのでイベントにしない
                event = {
                    "alias": self.alias,
                    "name": self.name,
                    "event": state.lower(),          # "locked" | "unlocked"
                    "from": prev.lower(),
                    "position": st["position"],
                    "battery_pct": st["battery_pct"],
                    "ts": self.last_change_ts,
                }
                if self.last_cmd and time.monotonic() - self.last_cmd[2] < 20 and self.last_cmd[1] == state.lower()[:-2]:
                    event["by"] = self.last_cmd[0]   # 直近 20 秒以内の遠隔コマンドが原因
                    self.last_cmd = None
                self.pub.publish(f"{self.alias}/event", event)
                log.info("[%s] EVENT %s → %s", self.alias, prev, state)
        self.pub.publish(f"{self.alias}/status", self.status_payload(st), retain=True)

    def on_mech_setting(self, setting: dict):
        self.pub.publish(f"{self.alias}/setting", {**setting, "ts": now_iso()}, retain=True)

    def note_command(self, user: str, action: str):
        self.last_cmd = (user, action, time.monotonic())

    def set_connected(self, flag: bool):
        if flag != self.connected:
            self.connected = flag
            self.pub.publish(f"{self.alias}/availability", "online" if flag else "offline", retain=True)

    def republish(self):
        if self.last_status is not None:
            self.pub.publish(f"{self.alias}/status", self.status_payload(self.last_status), retain=True)


# ---- BLE 接続ループ -----------------------------------------------------------
async def run_connection(tr: DeviceTracker, ble_cfg: dict):
    """1 回の BLE 接続を維持する。切断されたら戻る。"""
    loop = asyncio.get_running_loop()
    disconnected = asyncio.Event()
    got_random = asyncio.Event()
    sess = SesameSession(tr.secret)
    link = None

    def on_disconnect(_client):
        loop.call_soon_threadsafe(disconnected.set)

    def on_notify(_sender, data: bytearray):
        try:
            op, item, payload = sess.handle_notification(bytes(data))
        except Exception as e:  # noqa: BLE001
            log.error("[%s] 通知の解析に失敗: %s raw=%s", tr.alias, e, bytes(data).hex())
            return
        if op == OP_PUBLISH and item == ITEM_INITIAL:
            got_random.set()
        elif op == OP_PUBLISH and item == ITEM_MECH_STATUS and sess.mech_status:
            tr.on_mech_status(sess.mech_status)
        elif sess.mech_setting and item == 80:
            tr.on_mech_setting(sess.mech_setting)
        if link is not None:
            link.feed(op, item, payload)

    log.info("[%s] %s を探索中...", tr.alias, tr.mac)
    device = await BleakScanner.find_device_by_address(tr.mac, timeout=float(ble_cfg.get("scan_timeout_sec", 20)))
    if device is None:
        raise RuntimeError("スキャンで見つかりません")

    async with BleakClient(device, disconnected_callback=on_disconnect,
                           timeout=float(ble_cfg.get("connect_timeout_sec", 20))) as client:
        await client.start_notify(STATUS_CHAR_UUID, on_notify)
        await asyncio.wait_for(got_random.wait(), timeout=10)
        await client.write_gatt_char(CMD_CHAR_UUID, sess.login_packet(), response=False)
        log.info("[%s] 接続・ログイン完了。通知待機中。", tr.alias)
        link = LiveLink(client, sess)
        tr.link = link
        tr.set_connected(True)

        # status_republish_sec > 0 のときだけ、状態が変わらなくても定期的に status を再送する。
        # 0（既定）なら再送せず、BLE 通知が来たときだけ publish する。生存確認は heartbeat / LWT で行う。
        republish = float(ble_cfg.get("status_republish_sec", 0))
        if republish > 0:
            while not disconnected.is_set():
                try:
                    await asyncio.wait_for(disconnected.wait(), timeout=republish)
                except asyncio.TimeoutError:
                    tr.republish()
        else:
            await disconnected.wait()
    tr.link = None
    log.warning("[%s] BLE 切断", tr.alias)


async def device_loop(tr: DeviceTracker, ble_cfg: dict, stop: asyncio.Event, start_delay: float = 0):
    if start_delay:
        await asyncio.sleep(start_delay)
    backoff = float(ble_cfg.get("reconnect_min_sec", 3))
    backoff_max = float(ble_cfg.get("reconnect_max_sec", 60))
    while not stop.is_set():
        try:
            await run_connection(tr, ble_cfg)
            backoff = float(ble_cfg.get("reconnect_min_sec", 3))
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.error("[%s] 接続エラー: %s", tr.alias, e)
        tr.set_connected(False)
        if stop.is_set():
            break
        log.info("[%s] %.0f 秒後に再接続", tr.alias, backoff)
        try:
            await asyncio.wait_for(stop.wait(), timeout=backoff)
        except asyncio.TimeoutError:
            pass
        backoff = min(backoff * 2, backoff_max)


async def heartbeat_loop(pub: MqttPublisher, trackers: list, stop: asyncio.Event, interval=60, rc=None):
    started = time.time()
    while not stop.is_set():
        pub.publish("bridge/heartbeat", {
            "ts": now_iso(),
            "uptime_sec": int(time.time() - started),
            "mqtt_connected": pub.connected,
            "devices": {t.alias: {"ble_connected": t.connected, "state": t.last_stable_state} for t in trackers},
            "remote_control": rc.summary().get("remote_control") if rc else "n/a",
        }, retain=True)
        if rc and rc.active:
            pub.publish("bridge/authz", rc.summary(), retain=True)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def simulate_loop(trackers: list, stop: asyncio.Event):
    """BLE なしで、refSource/log.txt 由来の mechStatus を順に流す（MQTT 経路の確認用）。"""
    seq = ["fb0b0080030012", "fb0b0080a4ff54", "fb0b0080a8ff54", "fb0b00800b0012", "fb0b0080050012"]
    for tr in trackers:
        tr.set_connected(True)
    i = 0
    while not stop.is_set():
        st = parse_mech_status(bytes.fromhex(seq[i % len(seq)]))
        for tr in trackers:
            tr.on_mech_status(st)
        i += 1
        try:
            await asyncio.wait_for(stop.wait(), timeout=10)
        except asyncio.TimeoutError:
            pass


async def main_async(cfg: dict, simulate: bool, cfg_dir: str) -> int:
    if simulate:
        # 本番ブリッジと衝突しないよう、クライアント ID とトピック接頭辞を分ける
        cfg = {**cfg, "mqtt": {**cfg["mqtt"],
                               "client_id": (cfg["mqtt"].get("client_id") or "sesame-bridge") + "-sim",
                               "topic_prefix": cfg["mqtt"]["topic_prefix"].rstrip("/") + "/sim"}}
        log.warning("--simulate: topic_prefix=%s client_id=%s（本番とは別系統）",
                    cfg["mqtt"]["topic_prefix"], cfg["mqtt"]["client_id"])
    pub = MqttPublisher(cfg["mqtt"])
    pub.start()
    trackers = [DeviceTracker(d, pub) for d in cfg["devices"]]
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    rc = RemoteControl(cfg, cfg_dir, pub, trackers, simulate)
    rc.start()
    tasks = [asyncio.create_task(heartbeat_loop(pub, trackers, stop, rc=rc))]
    if rc.active:
        tasks.append(asyncio.create_task(rc.worker(stop)))
    if simulate:
        tasks.append(asyncio.create_task(simulate_loop(trackers, stop)))
    else:
        if BleakClient is None:
            log.error("bleak が見つかりません: pip install bleak")
            return 2
        # 同時に connect すると BlueZ が InProgress を返すため、開始を 3 秒ずつずらす
        tasks += [asyncio.create_task(device_loop(t, cfg.get("ble", {}), stop, start_delay=3 * i))
                  for i, t in enumerate(trackers)]

    await stop.wait()
    log.info("停止します")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    for t in trackers:
        t.set_connected(False)
    pub.stop()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default="config.json")
    ap.add_argument("--simulate", action="store_true", help="BLE を使わず擬似状態を publish する")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    level = "DEBUG" if args.verbose else cfg.get("log_level", "INFO")
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    import os
    sys.exit(asyncio.run(main_async(cfg, args.simulate, os.path.dirname(os.path.abspath(args.config)))))


if __name__ == "__main__":
    main()
