#!/usr/bin/env python3
"""
mqtt_push.py が MQTT に載せた配備データ（tar.gz）を受信し、SHA-256 を照合してから展開する（Pi 側）。

  python3 mqtt_pull.py <sha256> [--dir ~/sesame-bridge] [--timeout 20]

SHA-256 が一致しない場合は何も展開しない（公開ブローカー上での差し替え対策）。
"""
import argparse
import hashlib
import io
import json
import os
import ssl
import sys
import tarfile
import threading

import paho.mqtt.client as mqtt

HERE = os.path.dirname(os.path.abspath(__file__))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sha256")
    ap.add_argument("--dir", default=HERE)
    ap.add_argument("--timeout", type=float, default=20)
    ap.add_argument("-c", "--config", default=os.path.join(HERE, "config.json"))
    a = ap.parse_args()
    m = json.load(open(a.config, encoding="utf-8"))["mqtt"]
    topic = m["topic_prefix"].rstrip("/") + "/deploy/bundle"
    got = {}
    done = threading.Event()

    def on_connect(c, u, f, rc, p):
        c.subscribe(topic, qos=1)

    def on_message(c, u, msg):
        got["data"] = bytes(msg.payload)
        done.set()

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    if m.get("username"):
        c.username_pw_set(m["username"], m.get("password"))
    if m.get("tls", True):
        c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    c.on_connect, c.on_message = on_connect, on_message
    c.connect(m["host"], int(m["port"]), keepalive=30)
    c.loop_start()
    ok = done.wait(a.timeout)
    c.loop_stop(); c.disconnect()
    if not ok or not got.get("data"):
        print("配備データがありません（mqtt_push.py を先に実行）"); return 2
    data = got["data"]
    sha = hashlib.sha256(data).hexdigest()
    if sha != a.sha256.lower():
        print(f"SHA-256 不一致: 受信 {sha[:16]}… 期待 {a.sha256[:16]}…  展開しません"); return 3
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        names = [ti.name for ti in tar.getmembers()]
        for n in names:
            if "/" in n or n.startswith(".") or n in ("config.json", "authz.json"):
                print(f"不正なエントリ: {n}"); return 4
        tar.extractall(a.dir)
    print(f"展開 {len(names)} files → {a.dir}: {' '.join(names)}")
    print("PULL_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
