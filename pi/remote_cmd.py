#!/usr/bin/env python3
"""
署名付きの施錠 / 解錠コマンドを MQTT で送り、結果を待つクライアント（Mac / PC 用）。
スマホアプリが実装すべき手順と同じ（document/REMOTE_UNLOCK_DESIGN.md §5）。

  python3 remote_cmd.py alice sesame5_b lock
  python3 remote_cmd.py alice sesame5_b unlock --key keys/alice.pem

依存: pip install paho-mqtt pycryptodome
"""
import argparse
import json
import os
import secrets
import ssl
import sys
import threading
import time
import uuid

import paho.mqtt.client as mqtt
from Crypto.PublicKey import ECC

from authz import sign

HERE = os.path.dirname(os.path.abspath(__file__))


def load_config(path=None) -> dict:
    path = path or os.path.join(HERE, "config.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("user")
    ap.add_argument("lock", help="config.json の alias")
    ap.add_argument("action", choices=["lock", "unlock"])
    ap.add_argument("--key", help="秘密鍵 PEM（既定: keys/<user>.pem）")
    ap.add_argument("-c", "--config", default=None)
    ap.add_argument("--timeout", type=float, default=15.0)
    ap.add_argument("--mqtt-user", help="アプリ用の MQTT 認証情報（config.json と別にする場合）")
    ap.add_argument("--mqtt-pass")
    ap.add_argument("--sim", action="store_true", help="--simulate 中のブリッジ（接頭辞 /sim）に送る")
    a = ap.parse_args()

    cfg = load_config(a.config)
    m = cfg["mqtt"]
    prefix = m["topic_prefix"].rstrip("/") + ("/sim" if a.sim else "")
    key_path = a.key or os.path.join(HERE, "keys", f"{a.user}.pem")
    with open(key_path) as f:
        priv = ECC.import_key(f.read())

    cmd = {"v": 1, "req_id": uuid.uuid4().hex, "user": a.user, "lock": a.lock, "action": a.action,
           "ts": int(time.time()), "nonce": secrets.token_hex(12)}
    cmd["sig"] = sign(cmd, priv)

    result_topic = f"{prefix}/{a.lock}/cmd/result/{cmd['req_id']}"
    done = threading.Event()
    result = {}

    def on_connect(c, u, flags, rc, props):
        c.subscribe(result_topic, qos=1)

    def on_subscribe(c, u, mid, rcs, props):
        # 結果トピックの購読が確立してから publish（取りこぼし防止）
        c.publish(f"{prefix}/{a.lock}/cmd", json.dumps(cmd, ensure_ascii=False), qos=1)
        print(f"送信 {a.action} → {a.lock}  req_id={cmd['req_id'][:8]}…", flush=True)

    def on_message(c, u, msg):
        try:
            result.update(json.loads(msg.payload.decode()))
        except ValueError:
            result["raw"] = msg.payload.decode("utf-8", "replace")
        done.set()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    user, pw = a.mqtt_user or m.get("username"), a.mqtt_pass or m.get("password")
    if user:
        c.username_pw_set(user, pw)
    if m.get("tls", True):
        c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    c.on_connect, c.on_subscribe, c.on_message = on_connect, on_subscribe, on_message
    c.connect(m["host"], int(m["port"]), keepalive=30)
    c.loop_start()
    ok = done.wait(a.timeout)
    c.loop_stop(); c.disconnect()
    if not ok:
        print("結果が返りませんでした（ブリッジ停止、遠隔操作無効、または公開ブローカーで cmd 未購読）")
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
