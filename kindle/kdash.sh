#!/bin/sh
# Kindle dashboard: refresh at 06:00, 12:00, 18:00, 24:00 Europe/Madrid (+5 min, so GitHub has rendered)
trap '' HUP
D=/mnt/us/kdash
PID=/tmp/kdash.pid
TZSPEC="CET-1CEST,M3.5.0,M10.5.0/3"
OFFSET=300
[ -f $PID ] && kill -0 "$(cat $PID)" 2>/dev/null && exit 0
echo $$ > $PID
log() { echo "$(date '+%m-%d %H:%M:%S') $*" >> $D/log; }
[ "$(wc -c < $D/log 2>/dev/null || echo 0)" -gt 50000 ] && : > $D/log

secs_to_next() {
  t=$(TZ=$TZSPEC date '+%H %M %S')
  set -- $t
  h=${1#0}; m=${2#0}; s=${3#0}
  now=$(( ${h:-0}*3600 + ${m:-0}*60 + ${s:-0} ))
  for slot in 0 21600 43200 64800 86400; do
    tgt=$(( slot + OFFSET ))
    [ $tgt -gt $now ] && { echo $(( tgt - now )); return; }
  done
  echo 21600
}

sleep ${KDASH_BOOT_WAIT:-45}   # let framework/wifi come up
while true; do
  URL=$(cat $D/url)
  lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
  lipc-set-prop com.lab126.wifid enable 1 2>/dev/null
  ok=0; n=0
  while [ $n -lt 6 ] && [ $ok -eq 0 ]; do
    rm -f /tmp/kdash.png
    if $D/curl -sS -m 60 --cacert $D/cacert.pem -o /tmp/kdash.png "$URL" && [ -s /tmp/kdash.png ]; then ok=1; else n=$((n+1)); sleep 15; fi
  done
  if [ $ok -eq 1 ]; then
    /usr/sbin/eips -c; sleep 1
    /usr/sbin/eips -f -g /tmp/kdash.png
    w=$(secs_to_next)
    log "ok batt=$(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null) next_in=${w}s"
  else
    w=600
    log "fetch failed, retry in 10 min"
  fi
  sleep $w
done
