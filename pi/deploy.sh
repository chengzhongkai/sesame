#!/usr/bin/env bash
# pi/ 一式を Raspberry Pi の ~/sesame-bridge に配備する。
#
#   deploy.sh ssh   [--restart]   # ssh/scp で転送（PI_PASS を設定すると expect で自動入力）
#   deploy.sh clip                # tar+base64 のヒアドキュメントをクリップボードへ。
#                                 # Raspberry Pi Connect の Remote shell に貼り付けて展開する
#
# config.json（secret 入り）も一緒に送る。git には含まれない。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PI_HOST="${PI_HOST:-240b:10:ef27:ab00:dea6:32ff:feab:7777}"
PI_USER="${PI_USER:-cheng}"
REMOTE_DIR="sesame-bridge"
FILES=(sesame_protocol.py sesame_status.py sesame_mqtt_bridge.py mqtt_watch.py lock_status.py parse_share_url.py requirements.txt sesame-bridge.service config.json)

[[ -f "$HERE/config.json" ]] || { echo "pi/config.json がありません（config.example.json をコピーして作成）" >&2; exit 1; }

# Pi 側で展開後に実行するセットアップ
REMOTE_SETUP='cd ~/'"$REMOTE_DIR"' && python3 -c "import bleak, Crypto, paho.mqtt" 2>/dev/null || pip3 install -q --user --break-system-packages bleak pycryptodome paho-mqtt; python3 -m py_compile ~/'"$REMOTE_DIR"'/*.py && echo DEPLOY_OK'

run() {  # PI_PASS があれば expect でパスワードを自動入力
  if [[ -n "${PI_PASS:-}" ]]; then
    expect -f /dev/stdin -- "$@" <<'EXP'
      set timeout 120
      spawn {*}$argv
      expect {
        -re {[Pp]assword:} { send "$env(PI_PASS)\r"; exp_continue }
        eof
      }
      catch wait result
      exit [lindex $result 3]
EXP
  else
    "$@"
  fi
}

mode="${1:-ssh}"; shift || true
case "$mode" in
  ssh)
    SSH_OPTS=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
    run ssh "${SSH_OPTS[@]}" "$PI_USER@$PI_HOST" "mkdir -p ~/$REMOTE_DIR"
    run scp "${SSH_OPTS[@]}" "${FILES[@]/#/$HERE/}" "$PI_USER@[$PI_HOST]:~/$REMOTE_DIR/"
    extra="$REMOTE_SETUP"
    [[ "${1:-}" == "--restart" ]] && extra="$extra && sudo systemctl restart sesame-bridge && systemctl is-active sesame-bridge"
    run ssh "${SSH_OPTS[@]}" "$PI_USER@$PI_HOST" "$extra"
    ;;
  clip)
    {
      printf "mkdir -p ~/%s && base64 -d <<'B64EOF' | tar xz -C ~/%s\n" "$REMOTE_DIR" "$REMOTE_DIR"
      (cd "$HERE" && COPYFILE_DISABLE=1 tar czf - "${FILES[@]}") | base64 -b 76
      printf "B64EOF\n%s\n" "$REMOTE_SETUP"
    } | pbcopy
    echo "クリップボードにコピーしました（$(pbpaste | wc -c | tr -d ' ') bytes）。Pi の Remote shell に貼り付けてください。"
    ;;
  *) echo "usage: deploy.sh ssh [--restart] | clip" >&2; exit 2 ;;
esac
