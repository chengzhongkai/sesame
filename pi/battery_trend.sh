#!/usr/bin/env bash
# bridge.log から錠ごとの電池残量を日別に集計する（その日の最初と最後の値）。
#
#   battery_trend.sh                      # sesame5_t と sesame5_b
#   battery_trend.sh sesame5_t            # 指定した alias だけ
#   LOG=/path/to/bridge.log battery_trend.sh
#
# % は電圧からの推定値。負荷が減ると電圧が戻り、% が上がって見えることがある。
# ブリッジは状態が変わったときだけ記録するため、開閉のない日は行が出ない。
set -euo pipefail
LOG="${LOG:-$HOME/sesame-bridge/bridge.log}"
[[ $# -gt 0 ]] || set -- sesame5_t sesame5_b

for alias in "$@"; do
  echo "== $alias"
  printf '%-10s  %-8s %4s %6s   %-8s %4s %6s\n' 日付 最初 % V 最後 % V
  grep -F "[$alias] " "$LOG" | grep -E "電圧 [0-9.]+V \(約[0-9]+%\)" | awk '
    {
      d = $1; t = substr($2, 1, 8)
      match($0, /電圧 [0-9.]+V/); v = substr($0, RSTART, RLENGTH); sub(/^電圧 /, "", v); sub(/V$/, "", v)
      match($0, /約[0-9]+%/);    p = substr($0, RSTART, RLENGTH); gsub(/[^0-9]/, "", p)
      if (!(d in fp)) { fp[d] = p; fv[d] = v; ft[d] = t }
      lp[d] = p; lv[d] = v; lt[d] = t
    }
    END { for (d in fp) printf "%-10s  %-8s %3s%% %6s   %-8s %3s%% %6s\n", d, ft[d], fp[d], fv[d], lt[d], lp[d], lv[d] }
  ' | sort
done
