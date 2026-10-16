#!/usr/bin/env python3
"""
Pi へのコード配備（ssh 不達時用）。ファイル群を tar.gz にして MQTT の retained メッセージに載せる。
Pi 側では mqtt_pull.py が受信・検証・展開する。

  python3 mqtt_push.py sesame_protocol.py sesame_mqtt_bridge.py remote_control.py authz.py
  → 表示される SHA-256 を Pi 側コマンドに渡す:
     python3 mqtt_pull.py <sha256>

- 配布するのはコードだけ。config.json / authz.json / 鍵は含めない（含めようとすると拒否）。
- 公開ブローカー上では第三者が差し替えられるため、Pi 側は SHA-256 が一致したときだけ展開する。
- 展開後は `python3 mqtt_push.py --clear` で retained を消す。
"""
import argparse
import hashlib
import io
import json
import os
import ssl
import sys
import tarfile
import time

import paho.mqtt.client as mqtt

HERE = os.path.dirname(os.path.abspath(__file__))
FORBIDDEN = {"config.json", "authz.json", "nonces.db", "audit.log"}


def client(m):
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    if m.get("username"):
        c.username_pw_set(m["username"], m.get("password"))
    if m.get("tls", True):
        c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    c.connect(m["host"], int(m["port"]), keepalive=30)
    c.loop_start()
    return c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*")
    ap.add_argument("--clear", action="store_true", help="retained の配備データを削除する")
    ap.add_argument("-c", "--config", default=os.path.join(HERE, "config.json"))
    a = ap.parse_args()
    m = json.load(open(a.config, encoding="utf-8"))["mqtt"]
    topic = m["topic_prefix"].rstrip("/") + "/deploy/bundle"

    c = client(m)
    if a.clear:
        c.publish(topic, b"", qos=1, retain=True).wait_for_publish()
        print("cleared", topic)
    else:
        if not a.files:
            sys.exit("ファイルを指定してください")
        for f in a.files:
            if os.path.basename(f) in FORBIDDEN or f.endswith(".pem"):
                sys.exit(f"{f} は配布禁止（秘密情報）")
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            for f in a.files:
                tar.add(os.path.join(HERE, f) if not os.path.isabs(f) else f, arcname=os.path.basename(f))
        data = buf.getvalue()
        sha = hashlib.sha256(data).hexdigest()
        c.publish(topic, data, qos=1, retain=True).wait_for_publish()
        print(f"published {len(data)} bytes ({len(a.files)} files) → {topic}")
        print(f"Pi 側: python3 mqtt_pull.py {sha}")
    time.sleep(0.5)
    c.loop_stop(); c.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
