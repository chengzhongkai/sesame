#!/usr/bin/env python3
"""
Sesame 5 / Sesame Touch の状態を BLE 経由で確認する CLI（Raspberry Pi 用）。

依存: pip install bleak pycryptodome

使い方:
  python3 sesame_status.py                 # スキャン + 既知デバイスへログインして状態取得
  python3 sesame_status.py --scan-only     # 周辺の Sesame デバイスを列挙するだけ
  python3 sesame_status.py -c config.json          # 鍵は config.json（git 管理外）に置く
  python3 sesame_status.py --device FA:EE:B1:3F:13:0F=<DEVICE_SECRET_HEX>
  python3 sesame_status.py --offline-test  # refSource/log.txt のパケットで復号ロジックを自己検証
"""
import argparse
import asyncio
import logging
import sys

from sesame_protocol import (
    ITEM_UNLOCK, SEG_ENCRYPTED, BleakClient, SesameSession, devices_from_config,
    format_status, load_config, parse_mech_status, query_device, scan,
)

LOG_DEVICE_MAC = "FA:EE:B1:3F:13:0F"   # refSource/log.txt を記録したデバイス


def offline_test(devices: dict) -> int:
    """refSource/log.txt に残っている実パケットで鍵導出と復号を検証する（当該デバイスの secret が必要）。"""
    secret = devices.get(LOG_DEVICE_MAC)
    if not secret:
        print(f"OFFLINE TEST: SKIP（config.json に {LOG_DEVICE_MAC} の secret がありません）")
        return 0
    sess = SesameSession(secret)
    packets = [
        "03080e8e4b3f7c",                 # random code
        "055be9380e92ef281570a55b",       # login response
        "055284ab4bbfb8881fbbc86937",     # mech setting
        "0565a4a6ec6b26f4aa2fe4a72167",   # mech status (locked)
        "05c6c56849be706520",             # op8 item 92
    ]
    for p in packets:
        sess.handle_notification(bytes.fromhex(p))
    ok = True
    ok &= sess.session_key.hex() == "a2e26d6ea935bf713ff7fa043bd56544"
    ok &= sess.login_packet().hex() == "0302a2e26d6e"
    ok &= sess.login_ok and sess.mech_status["state"] == "LOCKED"
    # ログでは unlock 後に 0x54 のステータスが来ている → UNLOCKED になるか
    unlocked = parse_mech_status(bytes.fromhex("fb0b0080a4ff54"))
    ok &= unlocked["state"] == "UNLOCKED"
    # 送信側: ログの 1 発目 unlock パケット 050fe85988a1c8568b6b と一致するか
    sess.tx_counter = 0
    pkt = bytes([SEG_ENCRYPTED]) + sess.encrypt(bytes([ITEM_UNLOCK]) + b"\x03abc")
    ok &= pkt.hex() == "050fe85988a1c8568b6b"
    print("OFFLINE TEST:", "PASS" if ok else "FAIL")
    print("  session_key :", sess.session_key.hex())
    print("  device_time :", sess.device_time)
    print("  mechSetting :", sess.mech_setting)
    print("  mechStatus  :", format_status(sess.mech_status))
    print("  after unlock:", format_status(unlocked))
    print("  unlock pkt  :", pkt.hex())
    return 0 if ok else 1


def collect_devices(args) -> dict:
    devices = devices_from_config(load_config(args.config))
    for d in args.device or []:
        mac, _, sec = d.partition("=")
        devices[mac.upper()] = sec
    return devices


async def main_async(args) -> int:
    devices = collect_devices(args)

    found = await scan(args.scan_seconds)
    print("\n=== 周辺の Sesame デバイス ===")
    if not found:
        print("  （見つかりませんでした）")
    for mac, info in sorted(found.items(), key=lambda kv: -kv[1]["rssi"]):
        known = "鍵あり" if mac.upper() in devices else "鍵なし（スキャンのみ）"
        print(f"  {mac}  {info.get('model','?'):16s} RSSI {info['rssi']:4d}  "
              f"登録済={info.get('registered','?')}  name={info['name']!r}  [{known}]")

    if args.scan_only:
        return 0

    rc = 0
    print("\n=== 電子錠の状態 ===")
    for mac, secret in devices.items():
        if mac not in {m.upper() for m in found}:
            log.warning("[%s] スキャンで見つかりませんでしたが接続を試みます。", mac)
        try:
            sess = await query_device(mac, secret)
        except Exception as e:  # noqa: BLE001
            print(f"  {mac}: 取得失敗 ({e})")
            rc = 1
            continue
        if sess.mech_status:
            print(f"  {mac}: {format_status(sess.mech_status)}")
        else:
            print(f"  {mac}: ログイン={'OK' if sess.login_ok else 'NG'} / mechStatus 未受信")
            rc = 1
        if sess.mech_setting:
            print(f"      設定: {sess.mech_setting}")
        if sess.device_time:
            print(f"      デバイス時刻(UTC): {sess.device_time:%Y-%m-%d %H:%M:%S}")
    return rc


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default=None, help="config.json のパス（既定: スクリプトと同じ場所）")
    ap.add_argument("--scan-only", action="store_true", help="スキャンのみ（接続しない）")
    ap.add_argument("--scan-seconds", type=float, default=8.0)
    ap.add_argument("--device", action="append", metavar="MAC=SECRET_HEX", help="追加デバイス（複数可）")
    ap.add_argument("--offline-test", action="store_true", help="log.txt のパケットで自己検証")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if args.offline_test:
        sys.exit(offline_test(collect_devices(args)))
    if BleakClient is None:
        sys.exit("bleak が見つかりません: pip install bleak")
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
