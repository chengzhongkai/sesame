#!/usr/bin/env bash
# Sesame との常時 BLE 接続を省電力にする（BlueZ が錠を 11.25ms で叩き続けるのを止める）。
#
#   ble_lowpower.sh status   # 現在の設定と、保存済みの機器別パラメータを表示
#   ble_lowpower.sh apply    # main.conf の [LE] と bluetoothd の -P gap を設定（その後 Pi の再起動が必要）
#   ble_lowpower.sh revert   # main.conf を戻し、-P gap を外して bluetooth を再起動
#   ble_lowpower.sh verify   # ブリッジを再起動して、実際に使われた接続パラメータを btmon で確認
#
# Sesame 5 は GATT の Peripheral Preferred Connection Parameters（0x2a04）で 10〜12.5ms を公開している。
# BlueZ の gap プラグインがこれを読んで接続を 11.25ms・latency 0 に更新し、さらにカーネルに記憶させるため、
# 錠のリンク層からの 300〜500ms 要求が拒否される（Negative Reply）。結果、錠は 1 秒に約 89 回無線を起こす。
# 2026-10-07〜16 に Sesame 5 T の電池が約 3.4%/日 減った原因（btmon で確認）。
#
# 対策は 2 つ:
#   1. bluetoothd を -P gap で起動する（systemd の drop-in）。0x2a04 による更新を止める。
#   2. main.conf の [LE] で既定の接続パラメータを 400〜500ms にする。
#      錠の要求（300〜500ms・latency 0）がカーネルの上限内に収まり、受け入れられる。
# 適用後の実測（2026-10-16）: T 390ms・B 460ms・latency 0。
# カーネルに記憶済みの 10〜12.5ms は bluetoothd の再起動では消えないため、初回は Pi の再起動が必要。
set -euo pipefail

MIN_INTERVAL=320      # ×1.25ms = 400ms
MAX_INTERVAL=400      # ×1.25ms = 500ms
LATENCY=4             # スキップできる接続イベント数
SUP_TIMEOUT=800       # ×10ms = 8s（> (1+LATENCY)×MAX_INTERVAL×2 = 5s を満たす）

CONF=/etc/bluetooth/main.conf
BACKUP=/etc/bluetooth/main.conf.before-lowpower
DROPIN=/etc/systemd/system/bluetooth.service.d/no-gap-ppcp.conf
BRIDGE_DIR="$HOME/sesame-bridge"

restart_bridge() {
  pkill -f sesame_mqtt_bridge.py || true
  sleep 2
  cd "$BRIDGE_DIR"
  # 履歴を残すため追記（>>）で起動する
  nohup python3 sesame_mqtt_bridge.py -c config.json >> bridge.log 2>&1 &
  echo "ブリッジ再起動: PID $!"
}

show_status() {
  echo "== bluetoothd: $(bluetoothd --version 2>/dev/null || echo '?')"
  echo "== $CONF の [LE] 接続パラメータ"
  sudo awk '/^\[/{sec=$0} sec=="[LE]" && /^(Min|Max)ConnectionInterval|^Connection(Latency|SupervisionTimeout)/' "$CONF" || true
  echo "== bluetoothd の起動引数（-P gap が付いていること）"
  ps -o args= -C bluetoothd || true
  echo "== カーネルの既定値（期待値 $MIN_INTERVAL / $MAX_INTERVAL / $LATENCY / $SUP_TIMEOUT）"
  sudo sh -c 'cd /sys/kernel/debug/bluetooth/hci0 && for f in conn_min_interval conn_max_interval conn_latency supervision_timeout; do echo "$f = $(cat $f)"; done' || true
  echo "== 機器別に保存された接続パラメータ（あれば main.conf より優先される）"
  sudo grep -rs -A4 "ConnectionParameters" /var/lib/bluetooth/*/*/info || echo "（なし）"
}

write_conf() {
  [[ -f "$BACKUP" ]] || sudo cp -p "$CONF" "$BACKUP"
  sudo python3 - "$CONF" "$MIN_INTERVAL" "$MAX_INTERVAL" "$LATENCY" "$SUP_TIMEOUT" <<'PY'
import re, sys
path, mn, mx, lat, sup = sys.argv[1:]
keys = {"MinConnectionInterval": mn, "MaxConnectionInterval": mx,
        "ConnectionLatency": lat, "ConnectionSupervisionTimeout": sup}
lines = open(path).read().splitlines()
# 既存の（有効な）同名キーを消す
lines = [l for l in lines if not re.match(r"\s*(%s)\s*=" % "|".join(keys), l)]
# [LE] セクション（コメントアウトされていれば有効化）の直後に追記
idx = next((i for i, l in enumerate(lines) if re.match(r"\s*#?\s*\[LE\]\s*$", l)), None)
if idx is None:
    lines += ["", "[LE]"]
    idx = len(lines) - 1
else:
    lines[idx] = "[LE]"
lines[idx + 1:idx + 1] = [f"{k}={v}" for k, v in keys.items()]
open(path, "w").write("\n".join(lines) + "\n")
PY
}

write_dropin() {
  local orig
  orig=$(grep -m1 '^ExecStart=' /lib/systemd/system/bluetooth.service | cut -d= -f2-)
  sudo mkdir -p "$(dirname "$DROPIN")"
  printf '[Service]\nExecStart=\nExecStart=%s -P gap\n' "$orig" | sudo tee "$DROPIN" >/dev/null
  sudo systemctl daemon-reload
}

verify() {
  local out=/tmp/btmon-lowpower.txt
  sudo -v   # バックグラウンドの sudo がパスワード待ちで止まらないよう、先に認証しておく
  sudo timeout 60 btmon > "$out" 2>&1 &
  sleep 1
  restart_bridge
  echo "接続を待っています（約 50 秒）..."
  sleep 55
  echo "== 接続時のパラメータ（LE Connection Complete）と、その後の変更（Connection Update Complete）"
  grep -E -A12 "LE (Enhanced )?Connection Complete|LE Connection Update Complete" "$out" \
    | grep -E "Connection Complete|Update Complete|Peer address|Connection interval|Connection latency|Supervision timeout" || echo "（捕捉できず。$out を確認）"
  echo "== 錠からのパラメータ変更要求（あればカーネルが受け入れて上書きする）"
  grep -E -A6 "Connection Parameter Update Request" "$out" | grep -E "Request|interval|latency|timeout" || echo "（なし）"
  echo "== ブリッジログ"
  tail -n 8 "$BRIDGE_DIR/bridge.log"
}

case "${1:-status}" in
  status) show_status ;;
  apply)
    write_conf
    write_dropin
    echo "設定を書き込みました。カーネルに残った値を消すため、Pi を再起動してください（sudo reboot）。"
    echo "再起動後: $0 verify"
    ;;
  revert)
    [[ -f "$BACKUP" ]] || { echo "バックアップ $BACKUP がありません" >&2; exit 1; }
    sudo cp -p "$BACKUP" "$CONF"
    sudo rm -f "$DROPIN"
    sudo systemctl daemon-reload
    sudo systemctl restart bluetooth
    sleep 3
    restart_bridge
    ;;
  verify) verify ;;
  *) echo "usage: $0 {status|apply|revert|verify}" >&2; exit 1 ;;
esac
