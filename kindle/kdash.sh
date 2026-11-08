#!/bin/sh
# Kindle dashboard (screensaver mode).
# The Kindle sleeps normally and wakes by itself every few minutes (powerd/phd RTC housekeeping wakes).
# On every wake-up we check whether a new 6-hour slot (06/12/18/24 Europe/Madrid, +5 min) has started;
# if so we download the new image, store it as the screensaver and draw it right away.
# We never block sleep and never touch the WiFi (the OS reconnects it on resume).
trap '' HUP
D=/mnt/us/kdash
SS=/mnt/us/linkss/screensavers/weather.png
PID=/tmp/kdash.pid
TZSPEC="CET-1CEST,M3.5.0,M10.5.0/3"
OFFSET=300
[ -f $PID ] && kill -0 "$(cat $PID)" 2>/dev/null && exit 0
echo $$ > $PID
log() { echo "$(date '+%m-%d %H:%M:%S') $*" >> $D/log; }
[ "$(wc -c < $D/log 2>/dev/null || echo 0)" -gt 50000 ] && : > $D/log

# prints the id of the current slot, or nothing if we're inside the first OFFSET seconds of a slot
slot_id() {
  set -- $(TZ=$TZSPEC date '+%Y%m%d %H %M %S')
  h=${2#0}; m=${3#0}; s=${4#0}
  h=${h:-0}; m=${m:-0}; s=${s:-0}
  into=$(( (h % 6)*3600 + m*60 + s ))
  [ $into -lt $OFFSET ] && return
  echo "$1-$(( h / 6 ))"
}

do_update() {
  # wait (max 60s) for the OS to reconnect WiFi after resume
  n=0
  while [ $n -lt 20 ]; do
    [ "$(lipc-get-prop com.lab126.wifid cmState 2>/dev/null)" = "CONNECTED" ] && break
    n=$((n+1)); sleep 3
  done
  URL=$(cat $D/url); ok=0; t=0
  while [ $t -lt 3 ] && [ $ok -eq 0 ]; do
    rm -f /tmp/kdash.png.new
    if $D/curl -sS -m 40 --cacert $D/cacert.pem -o /tmp/kdash.png.new "$URL" && [ -s /tmp/kdash.png.new ]; then ok=1; else t=$((t+1)); sleep 5; fi
  done
  if [ $ok -eq 1 ]; then
    mv /tmp/kdash.png.new /tmp/kdash.png
    cp /tmp/kdash.png $SS.new && mv $SS.new $SS
    /usr/sbin/eips -f -g /tmp/kdash.png
    return 0
  fi
  return 1
}

check() {
  id=$(slot_id)
  [ -z "$id" ] && return
  [ "$id" = "$(cat $D/last_id 2>/dev/null)" ] && return
  if do_update; then
    echo "$id" > $D/last_id
    log "updated slot=$id batt=$(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null)"
  else
    log "fetch failed slot=$id (will retry on next wake)"
  fi
}

sleep ${KDASH_BOOT_WAIT:-45}
check
while true; do
  # block until the next resume/screensaver exit; the timeout keeps us alive if the event never comes
  lipc-wait-event -s 3600 com.lab126.powerd resuming,outOfScreenSaver >/dev/null 2>&1
  sleep 15   # let the system settle (WiFi reconnect starts on resume)
  check
done
