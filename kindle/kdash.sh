#!/bin/sh
# Kindle dashboard.
# - Fetch the image at 06:00, 12:00, 18:00, 24:00 Europe/Madrid (+5 min), WiFi on only for the fetch.
# - Between fetches, redraw the cached image every REDRAW seconds (covers the Kindle UI after button presses).
# - Self-updates this script from GitHub after each successful fetch.
trap '' HUP
D=/mnt/us/kdash
PID=/tmp/kdash.pid
TZSPEC="CET-1CEST,M3.5.0,M10.5.0/3"
OFFSET=300
REDRAW=180
SCRIPT_URL=https://raw.githubusercontent.com/vicentini-edoardo/Calendario/main/kindle/kdash.sh
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
  sleep 12   # wait for wifi association
  ok=0; n=0
  while [ $n -lt 6 ] && [ $ok -eq 0 ]; do
    rm -f /tmp/kdash.png.new
    if $D/curl -sS -m 60 --cacert $D/cacert.pem -o /tmp/kdash.png.new "$URL" && [ -s /tmp/kdash.png.new ]; then ok=1; else n=$((n+1)); sleep 15; fi
  done
  if [ $ok -eq 1 ]; then
    mv /tmp/kdash.png.new /tmp/kdash.png
    /usr/sbin/eips -c; sleep 1
    /usr/sbin/eips -f -g /tmp/kdash.png
    w=$(secs_to_next)
    log "ok batt=$(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null) next_in=${w}s"
    # self-update
    if $D/curl -sS -m 60 --cacert $D/cacert.pem -o $D/kdash.sh.new "$SCRIPT_URL" && sh -n $D/kdash.sh.new 2>/dev/null \
       && [ "$(cksum < $D/kdash.sh.new)" != "$(cksum < $D/kdash.sh)" ] && grep -q secs_to_next $D/kdash.sh.new; then
      mv $D/kdash.sh.new $D/kdash.sh; chmod +x $D/kdash.sh
      log "script updated, restarting"
      rm -f $PID
      KDASH_BOOT_WAIT=0 exec sh $D/kdash.sh
    fi
    rm -f $D/kdash.sh.new
  else
    w=600
    log "fetch failed, retry in 10 min"
  fi
  # Save battery: wifi off between updates (create /mnt/us/kdash/keepwifi to keep it on, e.g. for SSH)
  if [ ! -e $D/keepwifi ]; then
    sleep 3
    lipc-set-prop com.lab126.wifid enable 0 2>/dev/null
    log "wifi off"
  fi
  # wait until next slot, redrawing the cached image periodically
  while [ $w -gt 0 ]; do
    s=$REDRAW; [ $w -lt $s ] && s=$w
    sleep $s; w=$(( w - s ))
    [ $w -gt 0 ] && [ -s /tmp/kdash.png ] && /usr/sbin/eips -g /tmp/kdash.png
  done
done
