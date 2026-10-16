#!/usr/bin/env python3
"""
Sesame アプリの「鍵をシェア」リンク（ssm://UI?t=sk&sk=...&l=...&n=...）から
device secret と鍵の名前を取り出し、config.json の devices[] に追加する。

  python3 parse_share_url.py 'ssm://UI?t=sk&sk=BUuyc5N...&l=0&n=玄関上'
  python3 parse_share_url.py qr_screenshot.png            # QR 画像（スクリーンショット可）から直接読む
  python3 parse_share_url.py '<URL または画像>' --mac CC:AC:29:15:5A:E6 --alias upper_lock --save

- Sesame 5（OS3）の sk は base64 で 39 バイト: [0] productModel, [1:17] device secret(16B), [17:] 以降は鍵番号・デバイス UUID 等。
- 旧世代（OS2, Sesame 3/4）の 49 バイトは [0] 鍵番号, [1:17] secret, [17:49] アプリ秘密鍵。
- secret が正しいかは `sesame_status.py --device MAC=SECRET` でログインできるかで確認できる。
"""
import argparse
import base64
import json
import os
import sys
import urllib.parse

PRODUCT_MODELS = {5: "Sesame 5", 7: "Sesame 5 Pro", 9: "Sesame Touch Pro", 10: "Sesame Touch", 15: "Sesame 5 US"}
HERE = os.path.dirname(os.path.abspath(__file__))


def b64decode_urlsafe(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s)


def read_qr(path: str) -> str:
    """画像ファイルから QR の文字列を取り出す（OpenCV）。"""
    import cv2  # pip install opencv-python-headless
    img = cv2.imread(path)
    if img is None:
        raise ValueError(f"画像を読めません: {path}")
    det = cv2.QRCodeDetector()
    text, _, _ = det.detectAndDecode(img)
    if not text:
        # スクショは余白が多いので、拡大・グレースケールで再試行
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        for scale in (2, 0.5, 3):
            resized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            text, _, _ = det.detectAndDecode(resized)
            if text:
                break
    if not text:
        raise ValueError(f"QR を検出できません: {path}（QR 部分を大きく切り出した画像で再試行してください）")
    return text


def parse(url: str) -> dict:
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    if "sk" not in q:
        raise ValueError("リンクに sk パラメータがありません。アプリで表示されたリンク全体を貼ってください。")
    raw = b64decode_urlsafe(q["sk"][0])
    info = {"name": q.get("n", [""])[0], "level": q.get("l", [""])[0], "raw_len": len(raw), "raw_hex": raw.hex()}
    if len(raw) == 39:                       # SesameOS3（Sesame 5 系）
        info["format"] = "OS3"
        info["model"] = PRODUCT_MODELS.get(raw[0], f"model#{raw[0]}")
        info["secret"] = raw[1:17].hex()
        info["key_index"] = int.from_bytes(raw[17:19], "little")
        info["device_uuid_hex"] = raw[19:35].hex()
        info["tail_hex"] = raw[35:].hex()
        # BLE アドバタイズ名は UUID の後半 12 バイト + ff×4 を base64 したもの（実機で確認）。
        # sesame_status.py --scan-only の name と突き合わせれば MAC が特定できる。
        info["adv_name"] = base64.b64encode(raw[23:35] + b"\xff" * 4).decode().rstrip("=")
    elif len(raw) == 49:                     # SesameOS2
        info["format"] = "OS2"
        info["key_index"] = raw[0]
        info["secret"] = raw[1:17].hex()
        info["app_private_key"] = raw[17:49].hex()
    else:
        info["format"] = "unknown"
        info["secret"] = raw[1:17].hex()      # 推定。要ログイン確認
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url", help="ssm:// リンク、または QR 画像ファイルのパス")
    ap.add_argument("--mac", help="このデバイスの BLE MAC（sesame_status.py --scan-only で確認）")
    ap.add_argument("--alias", help="MQTT トピックに使う英数字の別名（例 upper_lock）")
    ap.add_argument("-c", "--config", default=os.path.join(HERE, "config.json"))
    ap.add_argument("--save", action="store_true", help="config.json の devices[] に追加/更新する")
    args = ap.parse_args()

    url = args.url
    if os.path.exists(url):
        url = read_qr(url)
        print(f"QR 読み取り : {url[:40]}…（{len(url)} 文字）")
    info = parse(url)
    print(f"形式       : {info['format']}（{info['raw_len']} バイト）")
    if "model" in info:
        print(f"機種       : {info['model']}")
    print(f"名前       : {info['name'] or '(なし)'}")
    print(f"secret     : {info['secret'][:4]}…{info['secret'][-4:]}（{len(info['secret']) // 2} バイト）")
    if "device_uuid_hex" in info:
        print(f"UUID       : {info['device_uuid_hex']}")
        print(f"BLE 名     : {info['adv_name']}   ← sesame_status.py --scan-only の name と一致する MAC がこの鍵")
    if info["format"] == "unknown":
        print("※ 未知の長さです。secret は推定なので、ログインできるか確認してください。", file=sys.stderr)

    if args.save:
        if not (args.mac and args.alias):
            print("--save には --mac と --alias が必要です", file=sys.stderr)
            return 2
        cfg = json.load(open(args.config, encoding="utf-8")) if os.path.exists(args.config) else {"devices": []}
        devices = cfg.setdefault("devices", [])
        entry = {"alias": args.alias, "name": info["name"], "mac": args.mac.upper(), "secret": info["secret"]}
        for i, d in enumerate(devices):
            if d["mac"].upper() == entry["mac"] or d["alias"] == entry["alias"]:
                devices[i] = {**d, **entry}
                break
        else:
            devices.append(entry)
        json.dump(cfg, open(args.config, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"保存しました: {args.config} → devices[{args.alias}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
