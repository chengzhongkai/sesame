#!/usr/bin/env python3
"""
Mac / PC から電子錠の現在状態を 1 回だけ取得して表示する。

ブローカーが保持している retained メッセージ（ブリッジが publish した最新状態）を読むだけなので、
Pi や Sesame に直接つながなくてよい。ブリッジが止まっていても最後の状態は見える。

依存: pip install paho-mqtt
使い方: python3 lock_status.py [-c config.json] [--json]
"""
import argparse
import datetime as dt
import json
import ssl
import sys
import threading

import paho.mqtt.client as mqtt



def load_config(path=None) -> dict:
    """config.json を読む（既定: このファイルと同じディレクトリ）。Mac 側は paho-mqtt 以外の依存を持たない。"""
    import os
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def age_text(ts_iso: str | None) -> str:
    if not ts_iso:
        return "不明"
    t = dt.datetime.fromisoformat(ts_iso)
    sec = int((dt.datetime.now(dt.timezone.utc) - t).total_seconds())
    if sec < 60:
        return f"{sec} 秒前"
    if sec < 3600:
        return f"{sec // 60} 分前"
    if sec < 86400:
        return f"{sec // 3600} 時間 {sec % 3600 // 60} 分前"
    return f"{sec // 86400} 日前"


def local_time(ts_iso: str | None) -> str:
    if not ts_iso:
        return "-"
    return dt.datetime.fromisoformat(ts_iso).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def fetch(cfg: dict, wait_sec: float = 5.0) -> dict:
    """prefix/# の retained メッセージを集めて {topic_suffix: payload} で返す。"""
    m = cfg["mqtt"]
    prefix = m["topic_prefix"].rstrip("/")
    got = {}
    done = threading.Event()

    def on_connect(c, u, flags, rc, props):
        c.subscribe(f"{prefix}/#", qos=1)

    def on_message(c, u, msg):
        suffix = msg.topic[len(prefix) + 1:]
        body = msg.payload.decode("utf-8", "replace")
        try:
            body = json.loads(body)
        except ValueError:
            pass
        got[suffix] = body
        # 欲しいものが揃ったら早めに終わる
        if all(f"{d['alias']}/status" in got for d in cfg["devices"]) and "bridge/availability" in got:
            done.set()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    if m.get("username"):
        c.username_pw_set(m["username"], m.get("password"))
    if m.get("tls", True):
        c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(m["host"], int(m["port"]), keepalive=30)
    c.loop_start()
    done.wait(wait_sec)
    c.loop_stop()
    c.disconnect()
    return got


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-c", "--config", default=None, help="config.json（既定: スクリプトと同じ場所）")
    ap.add_argument("--json", action="store_true", help="生の JSON を出力")
    ap.add_argument("--wait", type=float, default=5.0, help="最大待ち秒数")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if not cfg:
        print("config.json が見つかりません", file=sys.stderr)
        return 2

    got = fetch(cfg, args.wait)
    if args.json:
        print(json.dumps(got, ensure_ascii=False, indent=2))
        return 0

    bridge = got.get("bridge/availability", "不明")
    hb = got.get("bridge/heartbeat") or {}
    print(f"ブリッジ(Pi): {bridge}  最終ハートビート: {local_time(hb.get('ts'))} ({age_text(hb.get('ts'))})")

    rc = 0
    for d in cfg["devices"]:
        a = d["alias"]
        st = got.get(f"{a}/status")
        avail = got.get(f"{a}/availability", "不明")
        if not st:
            print(f"[{d.get('name') or a}] 状態なし（ブリッジがまだ publish していません）")
            rc = 1
            continue
        mark = {"LOCKED": "🔒 施錠", "UNLOCKED": "🔓 解錠"}.get(st["state"], "⚠ " + st["state"])
        warn = "  ⚠ 電池残量低" if st.get("battery_critical") else ""
        label = d.get("name") or st.get("name") or a   # ローカル config の名前を優先
        print(f"[{label}] {mark}   電池 {st['battery_pct']}% ({st['voltage']}V){warn}")
        print(f"      最終更新: {local_time(st.get('ts'))} ({age_text(st.get('ts'))})   "
              f"最終変化: {local_time(st.get('last_change_ts'))}   BLE: {avail}")
        if bridge != "online":
            print("      ※ ブリッジがオフラインのため、表示は最後に記録された状態です")
    return rc


if __name__ == "__main__":
    sys.exit(main())
