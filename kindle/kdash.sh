#!/bin/sh
# Kindle dashboard (deep-sleep mode with RTC alarm).
# The Kindle sleeps (suspend-to-RAM, WiFi off) and is woken by the pmic RTC alarm (rtc1) exactly when a new
# 6-hour slot (06/12/18/24 Europe/Madrid, +OFFSET) starts. On wake: WiFi on, download the new image,
# draw it with eips, stay awake ~AWAKE s (SSH possible), WiFi off, arm the next alarm, suspend again.
# The OS screensaver is disabled (preventScreenSaver) because this script controls suspend itself.
# Debug: touch /mnt/us/kdash/stay to keep the Kindle awake with WiFi on; /mnt/us/kdash/maxwait (seconds) caps the alarm.
trap '' HUP
D=/mnt/us/kdash
SS=/mnt/us/linkss/screensavers/weather.png
PID=/tmp/kdash.pid
TZSPEC="CET-1CEST,M3.5.0,M10.5.0/3"
OFFSET=300
AWAKE=60
RETRY=900
STALE_MAX=3
RTC=/sys/class/rtc/rtc1/wakealarm
[ -f $PID ] && kill -0 "$(cat $PID)" 2>/dev/null && exit 0
echo $$ > $PID
log() { echo "$(date '+%m-%d %H:%M:%S') $*" >> $D/log; }
[ "$(wc -c < $D/log 2>/dev/null || echo 0)" -gt 50000 ] && : > $D/log

# seconds elapsed in the current 6h slot (Madrid time)
into_slot() {
  set -- $(TZ=$TZSPEC date '+%H %M %S')
  h=${1#0}; m=${2#0}; s=${3#0}
  h=${h:-0}; m=${m:-0}; s=${s:-0}
  echo $(( (h % 6)*3600 + m*60 + s ))
}

# prints the id of the current slot, or nothing if we're inside the first OFFSET seconds of a slot
slot_id() {
  set -- $(TZ=$TZSPEC date '+%Y%m%d %H')
  h=${2#0}; h=${h:-0}
  [ "$(into_slot)" -lt $OFFSET ] && return
  echo "$1-$(( h / 6 ))"
}

wifi_wait() {
  n=0
  while [ $n -lt 20 ]; do
    [ "$(lipc-get-prop com.lab126.wifid cmState 2>/dev/null)" = "CONNECTED" ] && return 0
    n=$((n+1)); sleep 3
  done
  return 1
}

do_update() {
  wifi_wait
  URL=$(cat $D/url); ok=0; t=0; accept=0
  # the image must have been rendered for the current slot (marker file next to the PNG), else it is stale
  want=$(slot_id)
  while [ $t -lt 3 ] && [ $ok -eq 0 ]; do
    rm -f /tmp/kdash.png.new
    got=$($D/curl -sS -m 30 --cacert $D/cacert.pem "$URL.slot" 2>/dev/null)
    if [ "$got" != "$want" ]; then
      # GitHub cron can be late/dropped: after STALE_MAX stale attempts for this slot, accept the newest image anyway
      n=0; [ "$(cut -d: -f1 $D/stale 2>/dev/null)" = "$want" ] && n=$(cut -d: -f2 $D/stale)
      n=$((n+1)); echo "$want:$n" > $D/stale
      log "stale image (have=$got want=$want try=$n)"
      [ -z "$got" ] && return 1
      [ $n -lt $STALE_MAX ] && return 1
      [ "$got" = "$(cat $D/last_id 2>/dev/null)" ] && return 1
      accept=1
    fi
    if $D/curl -sS -m 40 --cacert $D/cacert.pem -o /tmp/kdash.png.new "$URL" && [ -s /tmp/kdash.png.new ]; then ok=1; else t=$((t+1)); sleep 5; fi
  done
  if [ $ok -eq 1 ]; then
    mv /tmp/kdash.png.new /tmp/kdash.png
    cp /tmp/kdash.png $SS.new && mv $SS.new $SS
    # stale image accepted as fallback: remember its slot so it is not re-downloaded, but keep retrying for the fresh one
    if [ $accept -eq 1 ]; then echo "$got" > $D/last_id; log "accepted stale image slot=$got (want=$want)"; return 1; fi
    return 0
  fi
  return 1
}

FAILED=0
check() {
  FAILED=0
  id=$(slot_id)
  [ -z "$id" ] && return
  [ "$id" = "$(cat $D/last_id 2>/dev/null)" ] && return
  if do_update; then
    echo "$id" > $D/last_id
    log "updated slot=$id batt=$(lipc-get-prop com.lab126.powerd battLevel 2>/dev/null)"
  else
    FAILED=1
    log "fetch failed slot=$id (retry in ${RETRY}s)"
  fi
}

# seconds to sleep: until next slot boundary + OFFSET + margin (or RETRY after a failed fetch)
next_wait() {
  [ $FAILED -eq 1 ] && { echo $RETRY; return; }
  i=$(into_slot)
  if [ $i -lt $OFFSET ]; then w=$(( OFFSET - i + 30 )); else w=$(( 21600 - i + OFFSET + 30 )); fi
  echo $w
}

sleep ${KDASH_BOOT_WAIT:-45}
while true; do
  lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null
  # stop the Kindle UI: its status bar would otherwise be repainted over the top of the image
  /etc/init.d/framework stop >/dev/null 2>&1
  lipc-set-prop com.lab126.wifid enable 1 2>/dev/null
  check
  # (re)draw the current image: after a resume the framework may have repainted the screen
  [ -f $SS ] && /usr/sbin/eips -f -g $SS
  sleep $AWAKE
  while [ -f $D/stay ]; do sleep 20; done
  sleep 5   # let the e-ink finish before suspending
  lipc-set-prop com.lab126.wifid enable 0 2>/dev/null
  sleep 3
  W=$(next_wait)
  [ -f $D/maxwait ] && M=$(cat $D/maxwait) && [ "$W" -gt "$M" ] && W=$M
  echo 0 > $RTC
  echo "+$W" > $RTC
  log "suspend for ${W}s"
  sync
  echo mem > /sys/power/state
  log "resumed"
  sleep 3
done
