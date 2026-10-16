#!/usr/bin/env python3
"""
遠隔施解錠の権限表（authz.json）を管理する CLI。

  authz_admin.py init                                   # authz.json を雛形から作成（enabled=true, allowed_actions=[lock]）
  authz_admin.py gen-key alice                          # 鍵ペア生成。秘密鍵は keys/alice.pem、公開鍵を表示（テスト・PC 用）
  authz_admin.py add alice <公開鍵 base64> [--tag MQTT:alice]
  authz_admin.py grant alice --locks sesame5_t,sesame5_b --actions lock,unlock \\
                 [--from 2026-10-01T00:00:00+09:00] [--until 2026-12-31T23:59:59+09:00] \\
                 [--days Tue,Fri] [--hours 09:00-12:00,18:00-20:00]
  authz_admin.py revoke alice            # ユーザーを無効化（enabled=false）。削除は --delete
  authz_admin.py enable / disable        # 全体のキルスイッチ
  authz_admin.py allow lock,unlock       # 全体で許可する操作（フェーズ制御）
  authz_admin.py list

authz.json はブリッジが更新を検知して自動で再読込する（再起動不要）。
"""
import argparse
import json
import os
import sys

from authz import generate_keypair, load_public_key

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = {
    "enabled": True,
    "allowed_actions": ["lock"],
    "clock_skew_sec": 60,
    "tz": "Asia/Tokyo",
    "limits": {"unlock_per_minute": 3, "unlock_per_hour": 20, "lock_per_minute": 10},
    "users": {},
}


def load(path):
    if not os.path.exists(path):
        sys.exit(f"{path} がありません。先に `authz_admin.py init` を実行してください")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, cfg):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)       # 書きかけをブリッジに読ませない
    print(f"保存: {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-f", "--file", default=os.path.join(HERE, "authz.json"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p = sub.add_parser("gen-key"); p.add_argument("user"); p.add_argument("--keys-dir", default=os.path.join(HERE, "keys"))
    p = sub.add_parser("add"); p.add_argument("user"); p.add_argument("pubkey"); p.add_argument("--tag")
    p = sub.add_parser("grant"); p.add_argument("user"); p.add_argument("--locks", required=True); p.add_argument("--actions", required=True)
    p.add_argument("--from", dest="valid_from"); p.add_argument("--until", dest="valid_until")
    p.add_argument("--days"); p.add_argument("--hours"); p.add_argument("--tz")
    p = sub.add_parser("revoke"); p.add_argument("user"); p.add_argument("--delete", action="store_true")
    p = sub.add_parser("activate"); p.add_argument("user")
    sub.add_parser("enable"); sub.add_parser("disable")
    p = sub.add_parser("allow"); p.add_argument("actions")
    sub.add_parser("list")
    a = ap.parse_args()

    if a.cmd == "init":
        if os.path.exists(a.file):
            sys.exit(f"{a.file} は既にあります")
        save(a.file, dict(TEMPLATE))
        return 0

    if a.cmd == "gen-key":
        os.makedirs(a.keys_dir, exist_ok=True)
        pem, pub = generate_keypair()
        path = os.path.join(a.keys_dir, f"{a.user}.pem")
        with open(path, "w") as f:
            f.write(pem)
        os.chmod(path, 0o600)
        print(f"秘密鍵: {path}（git 管理外。端末から出さないこと）")
        print(f"公開鍵: {pub}")
        print(f"登録:   python3 authz_admin.py add {a.user} {pub}")
        return 0

    cfg = load(a.file)
    users = cfg.setdefault("users", {})

    if a.cmd == "add":
        load_public_key(a.pubkey)           # 形式チェック
        u = users.setdefault(a.user, {"enabled": True, "grants": []})
        u["pubkey"] = a.pubkey
        u["enabled"] = True
        u["history_tag"] = (a.tag or f"MQTT:{a.user}")[:20]
        save(a.file, cfg)
    elif a.cmd == "grant":
        u = users.get(a.user) or sys.exit(f"ユーザー {a.user} がいません")
        g = {"locks": a.locks.split(","), "actions": a.actions.split(",")}
        for act in g["actions"]:
            if act not in ("lock", "unlock"):
                sys.exit(f"未知の action: {act}")
        if a.valid_from: g["valid_from"] = a.valid_from
        if a.valid_until: g["valid_until"] = a.valid_until
        if a.tz: g["tz"] = a.tz
        if a.days or a.hours:
            g["schedule"] = {}
            if a.days: g["schedule"]["days"] = a.days.split(",")
            if a.hours: g["schedule"]["hours"] = a.hours.split(",")
        u.setdefault("grants", []).append(g)
        save(a.file, cfg)
    elif a.cmd == "revoke":
        if a.user not in users:
            sys.exit(f"ユーザー {a.user} がいません")
        if a.delete:
            del users[a.user]
        else:
            users[a.user]["enabled"] = False
        save(a.file, cfg)
    elif a.cmd == "activate":
        users[a.user]["enabled"] = True
        save(a.file, cfg)
    elif a.cmd in ("enable", "disable"):
        cfg["enabled"] = a.cmd == "enable"
        save(a.file, cfg)
    elif a.cmd == "allow":
        acts = a.actions.split(",")
        for act in acts:
            if act not in ("lock", "unlock"):
                sys.exit(f"未知の action: {act}")
        cfg["allowed_actions"] = acts
        save(a.file, cfg)
    elif a.cmd == "list":
        print(f"enabled={cfg.get('enabled')} allowed_actions={cfg.get('allowed_actions')} tz={cfg.get('tz')}")
        for uid, u in users.items():
            print(f"- {uid}: enabled={u.get('enabled')} tag={u.get('history_tag')!r} pubkey={u.get('pubkey','')[:8]}…")
            for g in u.get("grants", []):
                extra = {k: v for k, v in g.items() if k not in ("locks", "actions")}
                print(f"    {','.join(g['locks'])} : {','.join(g['actions'])} {extra if extra else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
