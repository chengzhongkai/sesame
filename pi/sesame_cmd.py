#!/usr/bin/env python3
"""
Sesame 5 に BLE で施錠 / 解錠コマンドを送る検証用 CLI（Raspberry Pi 用）。

  python3 sesame_cmd.py sesame5_b lock                 # 施錠
  python3 sesame_cmd.py sesame5_b unlock               # 解錠
  python3 sesame_cmd.py sesame5_b unlock --relock 4    # 解錠して 4 秒後に再施錠（検証用）
  python3 sesame_cmd.py sesame5_b status               # 接続して状態を見るだけ

- 対象は config.json（git 管理外）の devices[].alias で指定する。
- 送信後、デバイスからの応答（op 7 / item 82|83、res 0 = 成功）と mechStatus の変化を待って表示する。
- 履歴タグは「長さ 1B + UTF-8」形式（refSource/log.txt で実績あり）。アプリの履歴に表示される。
- これは検証用。遠隔操作の本実装は document/REMOTE_UNLOCK_DESIGN.md に従う。
"""
import argparse
import asyncio
import logging
import sys
import time

from sesame_protocol import (
    CMD_CHAR_UUID, ITEM_INITIAL, ITEM_LOCK, ITEM_MECH_STATUS, ITEM_UNLOCK, OP_PUBLISH,
    OP_RESPONSE, SEG_ENCRYPTED, STATUS_CHAR_UUID, BleakClient, BleakScanner, SesameSession,
    format_status, load_config,
)

log = logging.getLogger("cmd")
ITEM_BY_ACTION = {"lock": ITEM_LOCK, "unlock": ITEM_UNLOCK}
EXPECT_STATE = {"lock": "LOCKED", "unlock": "UNLOCKED"}


def history_tag(text: str) -> bytes:
    raw = text.encode("utf-8")[:20]
    return bytes([len(raw)]) + raw


class Commander:
    def __init__(self, sess: SesameSession, client: BleakClient):
        self.sess = sess
        self.client = client
        self.responses = asyncio.Queue()
        self.statuses = asyncio.Queue()
        self.got_random = asyncio.Event()

    def on_notify(self, _sender, data: bytearray):
        try:
            op, item, payload = self.sess.handle_notification(bytes(data))
        except Exception as e:  # noqa: BLE001
            log.error("通知の解析に失敗: %s raw=%s", e, bytes(data).hex())
            return
        if op == OP_PUBLISH and item == ITEM_INITIAL:
            self.got_random.set()
        elif op == OP_RESPONSE and item in (ITEM_LOCK, ITEM_UNLOCK):
            self.responses.put_nowait((item, payload[0] if payload else None))
        elif op == OP_PUBLISH and item == ITEM_MECH_STATUS and self.sess.mech_status:
            self.statuses.put_nowait(dict(self.sess.mech_status))

    async def send(self, action: str, tag: str, timeout: float = 8.0) -> dict:
        item = ITEM_BY_ACTION[action]
        before = self.sess.mech_status["state"] if self.sess.mech_status else None
        packet = bytes([SEG_ENCRYPTED]) + self.sess.encrypt(bytes([item]) + history_tag(tag))
        t0 = time.monotonic()
        log.info("送信 %s（tag=%r, %d bytes）", action, tag, len(packet))
        await self.client.write_gatt_char(CMD_CHAR_UUID, packet, response=False)

        result = {"action": action, "state_before": before, "response": None, "state_after": None,
                  "elapsed_sec": None}
        # 応答（成功/失敗コード）
        try:
            r_item, res = await asyncio.wait_for(self.responses.get(), timeout=timeout)
            result["response"] = res
            log.info("応答 item=%d res=%s（%s）", r_item, res, "成功" if res == 0 else "失敗")
        except asyncio.TimeoutError:
            log.warning("応答がありません（%.0f 秒）", timeout)
        # 期待する状態になるまで mechStatus を待つ
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                st = await asyncio.wait_for(self.statuses.get(), timeout=max(0.1, deadline - time.monotonic()))
            except asyncio.TimeoutError:
                break
            log.info("状態 %s", format_status(st))
            result["state_after"] = st["state"]
            if st["state"] == EXPECT_STATE[action]:
                break
        result["elapsed_sec"] = round(time.monotonic() - t0, 2)
        return result


async def run(dev: dict, action: str, tag: str, relock: float, timeout: float) -> int:
    mac = dev["mac"].upper()
    sess = SesameSession(dev["secret"])
    log.info("[%s] %s を探索中...", dev["alias"], mac)
    device = await BleakScanner.find_device_by_address(mac, timeout=20)
    if device is None:
        log.error("スキャンで見つかりません")
        return 2
    async with BleakClient(device, timeout=20) as client:
        cmd = Commander(sess, client)
        await client.start_notify(STATUS_CHAR_UUID, cmd.on_notify)
        await asyncio.wait_for(cmd.got_random.wait(), timeout=10)
        await client.write_gatt_char(CMD_CHAR_UUID, sess.login_packet(), response=False)
        # ログイン直後の mechStatus（現在状態）を待つ
        try:
            st = await asyncio.wait_for(cmd.statuses.get(), timeout=8)
            log.info("現在 %s", format_status(st))
        except asyncio.TimeoutError:
            log.error("ログイン後の状態が届きません（secret が違う可能性）")
            return 3
        if action == "status":
            return 0

        rc = 0
        res = await cmd.send(action, tag, timeout)
        print(f"RESULT {res}")
        if res["response"] != 0 or res["state_after"] != EXPECT_STATE[action]:
            rc = 1
        if action == "unlock" and relock > 0:
            log.info("%.0f 秒後に再施錠します", relock)
            await asyncio.sleep(relock)
            res2 = await cmd.send("lock", tag, timeout)
            print(f"RESULT {res2}")
            if res2["response"] != 0 or res2["state_after"] != "LOCKED":
                log.error("再施錠を確認できませんでした。もう一度試します。")
                res3 = await cmd.send("lock", tag, timeout)
                print(f"RESULT {res3}")
                if res3["state_after"] != "LOCKED":
                    rc = 4
        await asyncio.sleep(0.5)
        await client.stop_notify(STATUS_CHAR_UUID)
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("alias", help="config.json の devices[].alias")
    ap.add_argument("action", choices=["lock", "unlock", "status"])
    ap.add_argument("--tag", default="MQTT", help="Sesame の履歴に残すタグ（20 バイトまで）")
    ap.add_argument("--relock", type=float, default=0, help="unlock 後に再施錠するまでの秒数（0 で再施錠しない）")
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("-c", "--config", default=None)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(args.config)
    dev = next((d for d in cfg.get("devices", []) if d["alias"] == args.alias), None)
    if not dev:
        sys.exit(f"alias {args.alias!r} が config.json にありません")
    if BleakClient is None:
        sys.exit("bleak が見つかりません")
    sys.exit(asyncio.run(run(dev, args.action, args.tag, args.relock, args.timeout)))


if __name__ == "__main__":
    main()
