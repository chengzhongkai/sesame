# Sesame 開閉履歴の確認手順

Raspberry Pi（chengRasp）上の MQTT ブリッジのログから、Sesame の施錠・解錠履歴を確認する手順。

## 1. Pi に入る

- **ssh**: `ssh cheng@240b:10:ef27:ab00:dea6:32ff:feab:7777`
  - Pi はグローバル IPv6 専用。Mac 側にも IPv6 が必要（iPhone テザリング等の IPv4 のみの回線では `No route to host`）。
- **Raspberry Pi Connect**: https://connect.raspberrypi.com/devices → chengRasp → Remote shell
  - Raspberry Pi ID でのログインが必要。

## 2. ブリッジの稼働とログの場所を確認

```bash
pgrep -af sesame_mqtt_bridge
for p in $(pgrep -f sesame_mqtt_bridge); do ls -l /proc/$p/fd/1 /proc/$p/fd/2; done
```

- 現状は nohup 起動（systemd 未登録）。ログは `~/sesame-bridge/bridge.log`。
- Pi が再起動するとブリッジは止まり、その間の履歴は残らない。最終起動は `uptime -s` で確認。

## 3. 開閉イベントを抽出

ブリッジは状態が変わるたびに `[<alias>] EVENT <前> → <後>` の行を出す。
alias は `sesame5_t`（Sesame 5 T）、`sesame5_b`（Sesame 5 B）。

```bash
# 直近 50 件
grep "sesame5_t\] EVENT" ~/sesame-bridge/bridge.log | tail -50

# 日ごとの件数（日付・遷移後の状態別）
grep "sesame5_t\] EVENT" ~/sesame-bridge/bridge.log | awk '{print $1, $NF}' | sort | uniq -c

# ログの開始時刻
head -1 ~/sesame-bridge/bridge.log | cut -c1-19
```

イベントが出ないときは、接続切れなどを確認する。

```bash
grep -E "sesame5_t" ~/sesame-bridge/bridge.log | grep -vE "MECH_STATUS|status" | tail -30
```

## 4. 遠隔操作（MQTT 経由）の記録

```bash
grep sesame5_t ~/sesame-bridge/audit.log 2>/dev/null | tail -20
```

`audit.log` は JSON Lines。誰が（`user`）、何を（`action`）、結果（`ok` / `code`）を記録する。

## 5. 電池残量の推移

```bash
# 日ごとの電池残量（その日の最初と最後の値）
grep "sesame5_t\] " ~/sesame-bridge/bridge.log | grep -o "^[0-9-]* .*約[0-9]*%" | awk '{d=$1; match($0,/約[0-9]+%/); p=substr($0,RSTART,RLENGTH); if(!(d in f)) f[d]=p; l[d]=p} END{for(d in f) print d, f[d], "→", l[d]}' | sort
```

2026-10-07〜16 は Sesame 5 T が約 3.4%/日 減った（71% → 40%）。
原因は BlueZ の gap プラグインで、錠が GATT で公開する推奨値（10〜12.5ms）に接続を更新し、錠自身の 300〜500ms 要求を拒否していた。
2026-10-16 に `pi/ble_lowpower.sh apply`（bluetoothd -P gap + main.conf の [LE]）と Pi 再起動で、T 390ms・B 460ms になった。
Pi を再起動したときはブリッジを手で起動し直す（nohup 起動のため）。

## 補足

- ブリッジのログに残るのは、ブリッジが BLE で接続していた間の状態変化だけ。
- 錠本体が保持する履歴（アプリの「履歴」画面と同じもの、手動・アプリ操作を含む）は BLE の `ITEM_HISTORY`（item code 4）で読み出せるが、未実装。
