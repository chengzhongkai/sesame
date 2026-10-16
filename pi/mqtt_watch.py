#!/usr/bin/env python3
"""
ブリッジが publish するトピックを購読して表示する確認ツール（Mac / PC 用）。
スマホアプリが購読する内容と同じものが見える。

依存: pip install paho-mqtt
使い方: python3 mqtt_watch.py -c config.json [--seconds 60]
"""
import argparse
import json
import ssl
import sys
import time

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default=None)
    ap.add_argument("--seconds", type=float, default=0, help="0 なら Ctrl-C まで")
    ap.add_argument("--sim", action="store_true", help="--simulate 中のブリッジ（接頭辞 /sim）を見る")
    args = ap.parse_args()
    cfg = load_config(args.config)["mqtt"]
    prefix = cfg["topic_prefix"].rstrip("/") + ("/sim" if args.sim else "")

    def on_connect(client, userdata, flags, rc, props):
        print(f"# connected rc={rc}, subscribing {prefix}/#", flush=True)
        client.subscribe(f"{prefix}/#", qos=1)

    def on_message(client, userdata, msg):
        topic = msg.topic[len(prefix) + 1:]
        body = msg.payload.decode("utf-8", "replace")
        try:
            body = json.dumps(json.loads(body), ensure_ascii=False)
        except ValueError:
            pass
        flag = " (retained)" if msg.retain else ""
        print(f"{time.strftime('%H:%M:%S')} {topic:28s}{flag} {body}", flush=True)

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311)
    if cfg.get("username"):
        c.username_pw_set(cfg["username"], cfg.get("password"))
    if cfg.get("tls", True):
        c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    c.on_connect = on_connect
    c.on_message = on_message
    c.connect(cfg["host"], int(cfg["port"]), keepalive=60)
    try:
        if args.seconds > 0:
            c.loop_start()
            time.sleep(args.seconds)
            c.loop_stop()
        else:
            c.loop_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
