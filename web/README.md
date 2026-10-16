# Sesame Remote（簡易 Web アプリ）

`index.html` 1 ファイルの静的 Web アプリ。ブラウザから MQTT over WebSocket でブリッジの状態を購読し、
Ed25519 で署名した施錠・解錠コマンドを送る（`document/REMOTE_UNLOCK_DESIGN.md` §5, §8 の参照実装）。

## 使い方

```bash
# どこかで静的配信する（例: Mac）
python3 -m http.server 8765 -d web
# → http://localhost:8765/ をスマホ・PC のブラウザで開く
```

Pi 上で配信してもよい（`python3 -m http.server 8765 -d ~/sesame-bridge/web`）。
HTTPS でない localhost 以外から開く場合、クリップボードコピー等が制限されることがある。

1. 設定に WebSocket URL（HiveMQ なら `wss://<cluster>:8884/mqtt`、公開 EMQX なら `wss://broker.emqx.io:8084/mqtt`）、
   トピック接頭辞、アプリ用 MQTT 認証情報、ユーザー ID を入れて「接続して保存」。
2. 「署名鍵」で鍵を生成し、表示された公開鍵を Pi で登録する:
   `python3 authz_admin.py add <ユーザー ID> <公開鍵>` → `grant …`
3. 錠カードの「施錠」はタップ、「解錠」は 1.2 秒の長押し。結果はカード下に表示される。

## 保存されるもの（ブラウザの localStorage のみ）

- `sesame.settings`: 接続設定（MQTT パスワードを含む）
- `sesame.key`: Ed25519 秘密鍵（base64）。**このブラウザプロファイルを使える人は解錠できる**。
  共有端末では使わない。端末を失くしたら Pi 側で `authz_admin.py revoke <user>`。

## 動作条件

- ボタンはブリッジが `bridge/authz` で `remote_control: active` を publish しているときだけ有効になる。
  公開ブローカーのままでは状態表示のみ（遠隔操作は設計上無効）。
- 表示される錠は、ブリッジが retained で publish している `<prefix>/<alias>/status` から自動で拾う。
