# Sesame 開閉履歴の確認手順

Raspberry Pi（chengRasp）上の MQTT ブリッジのログから、Sesame の施錠・解錠履歴を確認する手順。

## 1. Pi に入る

- **同じ AP（自宅 LAN）にいるとき**: `ssh cheng@192.168.0.229`
  - DHCP で IP が変わったら、MAC アドレスから探す: `ping -c1 192.168.0.255 >/dev/null; arp -an | grep -i dc:a6:32:ab:77:77`
- **外から ssh**: `ssh cheng@240b:10:ef27:ab00:dea6:32ff:feab:7777`
  - Mac 側にもグローバル IPv6 が必要（iPhone テザリング等の IPv4 のみの回線では `No route to host`）。
- **Raspberry Pi Connect**: https://connect.raspberrypi.com/devices → chengRasp → Remote shell
  - Raspberry Pi ID でのログインが必要。

## 2. ブリッジの稼働とログの場所を確認

```bash
pgrep -af sesame_mqtt_bridge
for p in $(pgrep -f sesame_mqtt_bridge); do ls -l /proc/$p/fd/1 /proc/$p/fd/2; done
```

- 現状は nohup 起動（systemd 未登録、2026-10-18 時点）。ログは `~/sesame-bridge/bridge.log`。
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
# 2 台の日別の電池残量（その日の最初と最後の値と電圧）
~/sesame-bridge/battery_trend.sh

# Mac から 1 行で（同じ AP にいるとき）
ssh cheng@192.168.0.229 '~/sesame-bridge/battery_trend.sh'
```

スクリプトは `pi/battery_trend.sh`（Pi には 2026-10-18 に配置済み）。

- % は電圧からの推定値。負荷が減ると電圧が戻り、% が上がって見えることがある。
- ブリッジは状態が変わったときだけ記録するため、開閉のない日は行が出ない。

### 経緯と基準値（BLE 省電力対策の効果確認用）

2026-10-07〜16 朝は 2 台とも約 3.3〜3.7%/日 減っていた（T 71% → 41%、B 91% → 58%）。
原因は BlueZ の gap プラグインで、錠が GATT で公開する推奨値（10〜12.5ms）に接続を更新し、錠自身の 300〜500ms 要求を拒否していた。
2026-10-16 午前に `pi/ble_lowpower.sh apply`（bluetoothd -P gap + main.conf の [LE]）と Pi 再起動で、T 390ms・B 460ms になった。

| 日付 | Sesame 5 T | Sesame 5 B | 備考 |
|---|---|---|---|
| 10/16 朝（対策前） | 41%（5.55V） | 58%（5.64V） | |
| 10/16 夜 | 48%（5.59V） | 65%（5.67V） | 負荷が減って電圧が戻った |
| 10/17 | 49% → 49%（5.60V） | 66% → 66%（5.68V） | 横ばい |

**1 週間後（2026-10-24 ごろ）の判定の目安**（10/17 の値と比べる）

- 1 週間で数 % 以内の減り: 対策は効いている。
- 1 日 1% 以上のペースで減っている: 接続間隔が戻っていないか確認する（`~/sesame-bridge/ble_lowpower.sh status`、`ps -o args= -C bluetoothd` に `-P gap` があるか）。

Pi を再起動したときは、ブリッジを手で起動し直す（systemd 未登録の間は nohup 起動のため）。

## 補足

- ブリッジのログに残るのは、ブリッジが BLE で接続していた間の状態変化だけ。
- 錠本体が保持する履歴（アプリの「履歴」画面と同じもの、手動・アプリ操作を含む）は BLE の `ITEM_HISTORY`（item code 4）で読み出せるが、未実装。
