#!/usr/bin/env python3
"""
Sesame 5（SesameOS3）の BLE プロトコル実装（Raspberry Pi 用、bleak + pycryptodome）。

- 鍵導出: session_key = AES-CMAC(device_secret, random_code)
- 暗号化: AES-CCM(session_key, nonce = counter(9B LE) + random_code(4B), AAD = 0x00, tag 4B)
- 参照: refSource/s5WinApp.py、document/MQTT_BRIDGE_DESIGN.md

依存: pip install bleak pycryptodome

プロトコルは refSource/s5WinApp.py（SesameOS3 / Sesame 5）に準拠。
"""
import argparse
import asyncio
import datetime as dt
import logging
import struct
import sys

from Crypto.Cipher import AES
from Crypto.Hash import CMAC

try:
    from bleak import BleakClient, BleakScanner
except ImportError:  # --offline-test だけなら bleak 不要
    BleakClient = BleakScanner = None

log = logging.getLogger("sesame")

# ---- 定数 -------------------------------------------------------------
SESAME_COMPANY_ID = 0x055A
CMD_CHAR_UUID = "16860002-a5ae-9856-b6d3-dbb4c676993e"
STATUS_CHAR_UUID = "16860003-a5ae-9856-b6d3-dbb4c676993e"

OP_RESPONSE = 7
OP_PUBLISH = 8
ITEM_LOGIN = 2
ITEM_HISTORY = 4
ITEM_VERSION = 5
ITEM_INITIAL = 14          # random_code 通知
ITEM_MECH_SETTING = 80
ITEM_MECH_STATUS = 81
ITEM_LOCK = 82
ITEM_UNLOCK = 83

SEG_PLAIN = 0x03           # 平文
SEG_ENCRYPTED = 0x05       # AES-CCM 暗号文

PRODUCT_MODELS = {
    0: "Sesame 3", 1: "WiFi Module 2", 2: "Sesame Bot", 3: "Sesame Bike",
    4: "Sesame Cycle", 5: "Sesame 5", 6: "Sesame Bike 2", 7: "Sesame 5 Pro",
    8: "Open Sensor", 9: "Sesame Touch Pro", 10: "Sesame Touch",
    11: "BLE Connector", 12: "Hub 3", 13: "Remote", 14: "Remote nano",
    15: "Sesame 5 US", 16: "Sesame Bot 2", 17: "Sesame Face Pro", 18: "Sesame Face",
}

# Sesame 5（CR123A x2）の電圧→残量の目安（CandyHouse SDK の換算表）
BATTERY_TABLE = [
    (5.85, 100), (5.82, 95), (5.79, 90), (5.76, 85), (5.73, 80), (5.70, 70),
    (5.65, 60), (5.60, 50), (5.55, 40), (5.50, 32), (5.40, 21), (5.20, 13),
    (5.10, 10), (5.00, 7), (4.80, 3), (4.60, 0),
]

# device secret はソースに書かない。git 管理外の config.json（devices[]）から読む。
def load_config(path: str | None = None) -> dict:
    """config.json を読む。path 未指定ならこのファイルと同じディレクトリの config.json。無ければ {}。"""
    import json, os
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def devices_from_config(cfg: dict) -> dict:
    """{MAC(大文字): secret_hex} を返す。"""
    return {d["mac"].upper(): d["secret"] for d in cfg.get("devices", []) if d.get("secret")}


# ---- 解析ヘルパ -------------------------------------------------------
def battery_percent(voltage: float) -> int:
    if voltage >= BATTERY_TABLE[0][0]:
        return 100
    for (v_hi, p_hi), (v_lo, p_lo) in zip(BATTERY_TABLE, BATTERY_TABLE[1:]):
        if voltage >= v_lo:
            return round(p_lo + (p_hi - p_lo) * (voltage - v_lo) / (v_hi - v_lo))
    return 0


def parse_mech_status(payload: bytes) -> dict:
    """Sesame 5 mechStatus: battery(u16) target(i16) position(i16) flags(u8)"""
    battery, target, position, flags = struct.unpack("<HhhB", payload[:7])
    voltage = battery * 2 / 1000
    st = {
        "battery_raw": battery,
        "voltage": round(voltage, 2),
        "battery_pct": battery_percent(voltage),
        "target": target,
        "position": position,
        "clutch_failed": bool(flags & 0x01),
        "in_lock_range": bool(flags & 0x02),
        "in_unlock_range": bool(flags & 0x04),
        "critical": bool(flags & 0x08),
        "stopped": bool(flags & 0x10),
        "battery_critical": bool(flags & 0x20),
        "clockwise": bool(flags & 0x40),
        "flags": flags,
    }
    if st["in_lock_range"]:
        st["state"] = "LOCKED"
    elif st["in_unlock_range"]:
        st["state"] = "UNLOCKED"
    else:
        st["state"] = "MOVING/UNKNOWN"
    return st


def parse_mech_setting(payload: bytes) -> dict:
    """Sesame 5 mechSetting: lock_position(i16) unlock_position(i16) auto_lock_sec(u16)"""
    lock_pos, unlock_pos = struct.unpack("<hh", payload[:4])
    setting = {"lock_position": lock_pos, "unlock_position": unlock_pos}
    if len(payload) >= 6:
        setting["auto_lock_sec"] = struct.unpack("<H", payload[4:6])[0]
    return setting


def format_status(st: dict) -> str:
    return (
        f"{st['state']}  電圧 {st['voltage']}V (約{st['battery_pct']}%)  "
        f"位置 {st['position']}° 目標 {st['target']}  "
        f"flags=0x{st['flags']:02x}"
        + ("  ⚠ 電池残量低" if st["battery_critical"] else "")
        + ("  ⚠ クラッチ異常" if st["clutch_failed"] else "")
    )


# ---- 暗号セッション（bleak 非依存、オフラインテスト可能） -------------------
class SesameSession:
    def __init__(self, device_secret_hex: str):
        self.device_secret = bytes.fromhex(device_secret_hex)
        self.random_code = None
        self.session_key = None
        self.tx_counter = 0
        self.rx_counter = 0
        self.mech_status = None
        self.mech_setting = None
        self.device_time = None
        self.login_ok = False
        self.events = []  # (op, item, payload)

    def set_random_code(self, code: bytes):
        self.random_code = code
        self.session_key = CMAC.new(self.device_secret, code, ciphermod=AES).digest()

    def _nonce(self, counter: int) -> bytes:
        return counter.to_bytes(9, "little") + self.random_code

    def encrypt(self, plain: bytes) -> bytes:
        c = AES.new(self.session_key, AES.MODE_CCM, nonce=self._nonce(self.tx_counter), mac_len=4)
        c.update(b"\x00")
        enc, tag = c.encrypt_and_digest(plain)
        self.tx_counter += 1
        return enc + tag

    def decrypt(self, data: bytes) -> bytes:
        c = AES.new(self.session_key, AES.MODE_CCM, nonce=self._nonce(self.rx_counter), mac_len=4)
        c.update(b"\x00")
        try:
            plain = c.decrypt_and_verify(data[:-4], data[-4:])
        except ValueError:
            log.warning("AES-CCM タグ検証に失敗（カウンタずれの可能性）。検証なしで復号します。")
            c = AES.new(self.session_key, AES.MODE_CCM, nonce=self._nonce(self.rx_counter), mac_len=4)
            c.update(b"\x00")
            plain = c.decrypt(data[:-4])
        self.rx_counter += 1
        return plain

    def login_packet(self) -> bytes:
        return bytes([SEG_PLAIN, ITEM_LOGIN]) + self.session_key[:4]

    def handle_notification(self, data: bytes):
        """BLE 通知 1 件を解析。戻り値は (op, item, payload)。"""
        seg = data[0]
        if seg == SEG_ENCRYPTED:
            body = self.decrypt(data[1:])
        else:
            body = data[1:]
        op, item, payload = body[0], body[1], body[2:]
        self.events.append((op, item, payload))

        if op == OP_PUBLISH and item == ITEM_INITIAL:
            self.set_random_code(payload[:4])
            log.info("random_code=%s session_key=%s", payload[:4].hex(), self.session_key.hex())
        elif op == OP_RESPONSE and item == ITEM_LOGIN:
            self.login_ok = payload[0] == 0
            if len(payload) >= 5:
                ts = struct.unpack("<I", payload[1:5])[0]
                self.device_time = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
            log.info("login result=%d device_time=%s", payload[0], self.device_time)
        elif op == OP_PUBLISH and item == ITEM_MECH_STATUS:
            self.mech_status = parse_mech_status(payload)
            log.info("mechStatus: %s", format_status(self.mech_status))
        elif op == OP_PUBLISH and item == ITEM_MECH_SETTING:
            self.mech_setting = parse_mech_setting(payload)
            log.info("mechSetting: %s", self.mech_setting)
        elif op == OP_RESPONSE and item in (ITEM_LOCK, ITEM_UNLOCK):
            log.info("%s response=%d", "lock" if item == ITEM_LOCK else "unlock", payload[0])
        else:
            log.debug("op=%d item=%d payload=%s", op, item, payload.hex())
        return op, item, payload


# ---- BLE 処理 ----------------------------------------------------------
def decode_adv(mfr: bytes) -> dict:
    """Sesame の manufacturer data: productModel(u16 LE) isRegistered(u8) ..."""
    info = {"raw": mfr.hex()}
    if len(mfr) >= 3:
        model = struct.unpack("<H", mfr[0:2])[0]
        info["model"] = PRODUCT_MODELS.get(model, f"model#{model}")
        info["registered"] = bool(mfr[2] & 0x01)
    return info


async def scan(seconds: float) -> dict:
    log.info("BLE スキャン中 (%.0f 秒)...", seconds)
    found = {}

    def cb(device, adv):
        mfr = adv.manufacturer_data.get(SESAME_COMPANY_ID)
        if mfr is None:
            return
        found[device.address] = {
            "name": adv.local_name or device.name or "",
            "rssi": adv.rssi,
            **decode_adv(mfr),
        }

    scanner = BleakScanner(cb)
    await scanner.start()
    await asyncio.sleep(seconds)
    await scanner.stop()
    return found


async def query_device(mac: str, secret_hex: str, timeout: float = 20.0) -> SesameSession:
    sess = SesameSession(secret_hex)
    got_random = asyncio.Event()
    got_status = asyncio.Event()

    def on_notify(_sender, data: bytearray):
        data = bytes(data)
        log.debug("notify raw=%s", data.hex())
        try:
            op, item, _ = sess.handle_notification(data)
        except Exception as e:  # noqa: BLE001
            log.error("通知の解析に失敗: %s (raw=%s)", e, data.hex())
            return
        if op == OP_PUBLISH and item == ITEM_INITIAL:
            got_random.set()
        if sess.mech_status is not None and sess.login_ok:
            got_status.set()

    log.info("[%s] 接続中...", mac)
    async with BleakClient(mac, timeout=timeout) as client:
        await client.start_notify(STATUS_CHAR_UUID, on_notify)
        await asyncio.wait_for(got_random.wait(), timeout=10)
        await client.write_gatt_char(CMD_CHAR_UUID, sess.login_packet(), response=False)
        try:
            await asyncio.wait_for(got_status.wait(), timeout=8)
        except asyncio.TimeoutError:
            log.warning("[%s] ログイン後の mechStatus 通知を受信できませんでした。", mac)
        await asyncio.sleep(0.5)
        await client.stop_notify(STATUS_CHAR_UUID)
    return sess


