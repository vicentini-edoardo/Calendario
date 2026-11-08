#!/usr/bin/env python3
"""Render a 600x800 greyscale weather + calendar screen for a Kindle 4."""
import calendar, json, sys, datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo
import requests, icalendar, recurring_ical_events
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
import os
# Config comes from the KINDLE_CONFIG env var (GitHub secret) or a local config.json
CFG = json.loads(os.environ["KINDLE_CONFIG"]) if os.environ.get("KINDLE_CONFIG") else json.loads((HERE / "config.json").read_text())
TZ = ZoneInfo(CFG["timezone"])
W, H = 600, 800
FONT_CANDIDATES = [
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
]
def font(size, bold=False):
    for reg, bld in FONT_CANDIDATES:
        p = bld if bold else reg
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    raise RuntimeError("No usable font found")

GIORNI = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]
GIORNI_LUNGHI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica"]
MESI = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio",
        "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

def wmo(code):
    """(descrizione, icona) from WMO weather code."""
    if code == 0: return "Sereno", "sun"
    if code in (1, 2): return "Poco nuvoloso", "partly"
    if code == 3: return "Nuvoloso", "cloud"
    if code in (45, 48): return "Nebbia", "fog"
    if code in (51, 53, 55, 56, 57): return "Pioviggine", "rain"
    if code in (61, 63, 65, 66, 67, 80, 81, 82): return "Pioggia", "rain"
    if code in (71, 73, 75, 77, 85, 86): return "Neve", "snow"
    if code in (95, 96, 99): return "Temporale", "storm"
    return "Variabile", "cloud"

def icon(d, kind, cx, cy, s):
    """Simple black line icons, s = half size."""
    def cloud(ox=0, oy=0, k=1.0):
        r = s * 0.45 * k
        d.ellipse([cx+ox-s*0.9*k, cy+oy-r*0.4, cx+ox-s*0.1*k, cy+oy+r*1.2], fill=0)
        d.ellipse([cx+ox-s*0.5*k, cy+oy-r*1.2, cx+ox+s*0.5*k, cy+oy+r*0.6+r*0.4], fill=0)
        d.ellipse([cx+ox+s*0.0*k, cy+oy-r*0.5, cx+ox+s*0.9*k, cy+oy+r*1.2], fill=0)
        d.rectangle([cx+ox-s*0.6*k, cy+oy+r*0.3, cx+ox+s*0.6*k, cy+oy+r*1.2], fill=0)
    def sun(ox=0, oy=0, k=1.0):
        r = s*0.45*k
        d.ellipse([cx+ox-r, cy+oy-r, cx+ox+r, cy+oy+r], outline=0, width=max(2, int(s/9)))
        import math
        for a in range(0, 360, 45):
            x1 = cx+ox+math.cos(math.radians(a))*r*1.4; y1 = cy+oy+math.sin(math.radians(a))*r*1.4
            x2 = cx+ox+math.cos(math.radians(a))*r*1.9; y2 = cy+oy+math.sin(math.radians(a))*r*1.9
            d.line([x1, y1, x2, y2], fill=0, width=max(2, int(s/10)))
    if kind == "sun": sun()
    elif kind == "partly": sun(-s*0.35, -s*0.3, 0.8); cloud(s*0.1, s*0.15, 0.85)
    elif kind == "cloud": cloud(0, -s*0.1)
    elif kind == "fog":
        for i in range(4): d.line([cx-s*0.8, cy-s*0.5+i*s*0.35, cx+s*0.8, cy-s*0.5+i*s*0.35], fill=0, width=max(2, int(s/9)))
    elif kind in ("rain", "storm", "snow"):
        cloud(0, -s*0.4)
        for i in range(3):
            x = cx - s*0.5 + i*s*0.5
            if kind == "snow":
                d.text((x-4, cy+s*0.35), "*", font=font(int(s*0.7), True), fill=0)
            else:
                d.line([x+s*0.15, cy+s*0.35, x-s*0.05, cy+s*0.8], fill=0, width=max(2, int(s/9)))
        if kind == "storm":
            d.polygon([(cx+s*0.1, cy+s*0.2), (cx-s*0.2, cy+s*0.75), (cx, cy+s*0.65), (cx-s*0.1, cy+s*1.05), (cx+s*0.3, cy+s*0.5), (cx+s*0.1, cy+s*0.55)], fill=0)

def get_weather():
    r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=20, params={
        "latitude": CFG["lat"], "longitude": CFG["lon"], "timezone": CFG["timezone"],
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,relative_humidity_2m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum",
        "hourly": "temperature_2m,precipitation_probability,precipitation,weather_code",
        "forecast_days": 2})
    r.raise_for_status()
    return r.json()

def get_events(start, end):
    out = []
    for cal_cfg in CFG["calendars"]:
        r = requests.get(cal_cfg["url"], timeout=30)
        r.raise_for_status()
        cal = icalendar.Calendar.from_ical(r.content)
        for ev in recurring_ical_events.of(cal).between(start, end):
            s = ev["DTSTART"].dt; e = ev.get("DTEND")
            e = e.dt if e else s
            allday = not isinstance(s, dt.datetime)
            if not allday:
                s = s.astimezone(TZ)
                e = e.astimezone(TZ)
            out.append({"start": s, "end": e, "allday": allday, "prio": cal_cfg.get("priority", False),
                        "title": str(ev.get("SUMMARY", "(senza titolo)"))})
    out.sort(key=lambda x: (dt.datetime.combine(x["start"], dt.time(), TZ) if x["allday"] else x["start"]))
    return out

def wrap(d, text, f, maxw, maxlines):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= maxw: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    if len(lines) > maxlines:
        lines = lines[:maxlines]; lines[-1] = fit(d, lines[-1] + "…", f, maxw)
    return lines

BANDS = [("Notte", 0, 6, 3), ("Mattina", 6, 12, 9), ("Pomeriggio", 12, 18, 15), ("Sera", 18, 24, 21)]
def band_stats(wx, day):
    h = wx["hourly"]; res = []
    for name, a, b, mid in BANDS:
        idx = [i for i, t in enumerate(h["time"]) if t.startswith(day.isoformat()) and a <= int(t[11:13]) < b]
        temps = [h["temperature_2m"][i] for i in idx]
        res.append({"name": name, "a": a, "b": b,
                    "tmin": min(temps), "tmax": max(temps),
                    "pp": max(h["precipitation_probability"][i] or 0 for i in idx),
                    "mm": sum(h["precipitation"][i] or 0 for i in idx),
                    "code": max((h["weather_code"][i] for i in idx), key=lambda c: (c >= 51, c))})
    return res

def event_days(ev):
    s = ev["start"] if ev["allday"] else ev["start"].date()
    e = ev["end"] if ev["allday"] else ev["end"].date()
    if ev["allday"] or e > s: e = e - dt.timedelta(days=1) if (ev["allday"] or ev["end"].time() == dt.time(0)) else e
    d = s
    while d <= max(s, e):
        yield d; d += dt.timedelta(days=1)

def fit(d, text, f, maxw):
    if d.textlength(text, font=f) <= maxw: return text
    while text and d.textlength(text + "…", font=f) > maxw: text = text[:-1]
    return text + "…"

def render(out_path):
    now = dt.datetime.now(TZ); today = now.date()
    try:
        wx = get_weather(); wx_err = None
    except Exception as ex:
        wx, wx_err = None, str(ex)
    month_start = today.replace(day=1)
    horizon = today + dt.timedelta(days=60)
    try:
        events = get_events(dt.datetime.combine(month_start, dt.time(), TZ), dt.datetime.combine(horizon, dt.time(), TZ))
        ev_err = None
    except Exception as ex:
        events, ev_err = [], str(ex)

    img = Image.new("L", (W, H), 255); d = ImageDraw.Draw(img)
    # Header
    d.text((24, 14), f"{GIORNI_LUNGHI[today.weekday()]} {today.day} {MESI[today.month]}", font=font(34, True), fill=0)
    d.text((W-24, 24), now.strftime("%H:%M"), font=font(22), fill=90, anchor="ra")
    d.line([24, 62, W-24, 62], fill=0, width=3)

    # Lunch (priority calendar)
    y = 70
    lunch_day = today
    while lunch_day.weekday() >= 5 or (lunch_day == today and not any(e["prio"] and lunch_day in set(event_days(e)) for e in events) and lunch_day.weekday() < 5 and False):
        lunch_day += dt.timedelta(days=1)
    lunch = [e for e in events if e["prio"] and lunch_day in set(event_days(e))]
    BH = 128
    d.rounded_rectangle([24, y, W-24, y+BH], radius=10, outline=0, width=4)
    lab = "PRANZO OGGI" if lunch_day == today else f"PRANZO {GIORNI[lunch_day.weekday()].upper()} {lunch_day.day}/{lunch_day.month}"
    tw = int(d.textlength(lab, font=font(17, True))) + 24
    d.rounded_rectangle([24, y, 24+tw, y+28], radius=10, fill=0)
    d.rectangle([24, y+14, 24+tw, y+28], fill=0)
    d.text((36, y+4), lab, font=font(17, True), fill=255)
    if lunch:
        txt = lunch[0]["title"].replace("Comedor:", "").strip()
        parts = [p.strip() for p in txt.split(" / ")]
        ly = y + 36
        for k, p in enumerate(parts[:2]):
            for ln in wrap(d, ("1° " if k == 0 else "2° ") + p, font(19, True), W-72, 2):
                d.text((38, ly), ln, font=font(19, True), fill=0); ly += 24
            ly += 4
    else:
        d.text((38, y+48), "Nessun menù", font=font(21), fill=90)
    y += BH + 12

    # Weather: today
    if wx:
        c = wx["current"]; dly = wx["daily"]; desc, ic = wmo(c["weather_code"])
        icon(d, ic, 70, y+52, 46)
        d.text((135, y-4), f"{round(c['temperature_2m'])}°", font=font(78, True), fill=0)
        d.text((290, y+4), f"{CFG['city']} · {desc}", font=font(22, True), fill=0)
        d.text((290, y+36), f"Min {round(dly['temperature_2m_min'][0])}°   Max {round(dly['temperature_2m_max'][0])}°", font=font(30, True), fill=0)
        d.text((290, y+76), f"Pioggia oggi {dly['precipitation_probability_max'][0]}% · {dly['precipitation_sum'][0]:.1f} mm", font=font(18), fill=40)
        y += 112
        bands = band_stats(wx, today)
        cw = (W-48)/4
        d.line([24, y, W-24, y], fill=170, width=1)
        for i, bd in enumerate(bands):
            x0 = 24 + cw*i; cx = x0 + cw/2
            if i: d.line([x0, y+6, x0, y+150], fill=200, width=1)
            now_in = bd["a"] <= now.hour < bd["b"]
            if now_in:
                d.rounded_rectangle([x0+8, y+6, x0+cw-8, y+32], radius=6, fill=0)
            d.text((cx, y+8), bd["name"], font=font(17, True), fill=255 if now_in else 0, anchor="ma")
            icon(d, wmo(bd["code"])[1], cx, y+68, 24)
            d.text((cx, y+100), f"{round(bd['tmin'])}° / {round(bd['tmax'])}°", font=font(19, True), fill=0, anchor="ma")
            d.text((cx, y+124), f"{bd['pp']}%  ·  {bd['mm']:.1f} mm", font=font(16), fill=40, anchor="ma")
        y += 156
    else:
        d.text((24, y+10), "Meteo non disponibile", font=font(24, True), fill=0)
        d.text((24, y+44), (wx_err or "")[:70], font=font(14), fill=90)
        y += 100
    d.line([24, y, W-24, y], fill=0, width=3)

    # Month grid (regular calendar only)
    normal = [e for e in events if not e["prio"]]
    by_day = {}
    for ev in normal:
        for day in event_days(ev): by_day.setdefault(day, []).append(ev)
    gy = y + 8
    d.text((24, gy), f"{MESI[today.month]} {today.year}", font=font(22, True), fill=0)
    gy += 32
    cw = (W-48)/7
    for i, g in enumerate(GIORNI):
        d.text((24+cw*i+cw/2, gy), g.upper(), font=font(13, True), fill=90, anchor="ma")
    gy += 19
    weeks = calendar.Calendar(0).monthdayscalendar(today.year, today.month)
    rh = 31
    for wk in weeks:
        for i, dn in enumerate(wk):
            if not dn: continue
            cx = 24 + cw*i + cw/2; day = dt.date(today.year, today.month, dn)
            if day == today:
                d.rounded_rectangle([cx-19, gy-2, cx+19, gy+rh-7], radius=7, fill=0)
                d.text((cx, gy), str(dn), font=font(20, True), fill=255, anchor="ma")
            else:
                d.text((cx, gy), str(dn), font=font(20), fill=150 if day < today else 0, anchor="ma")
            if day in by_day:
                d.ellipse([cx-3, gy+rh-12, cx+3, gy+rh-6], fill=255 if day == today else 0)
        gy += rh
    d.line([24, gy+2, W-24, gy+2], fill=0, width=3)

    # Upcoming events (regular calendar)
    ey = gy + 8
    d.text((24, ey), "Prossimi eventi", font=font(20, True), fill=0)
    ey += 30
    if ev_err:
        d.text((24, ey), "Calendario non disponibile", font=font(18), fill=90)
    else:
        shown = 0; last_day = None
        for day in sorted(k for k in by_day if k >= today):
            for ev in by_day[day]:
                if ey > H - 28: break
                if day != last_day:
                    label = "Oggi" if day == today else ("Domani" if day == today + dt.timedelta(days=1) else f"{GIORNI[day.weekday()].capitalize()} {day.day}/{day.month}")
                    d.text((24, ey), label, font=font(16, True), fill=70); last_day = day
                t = "" if ev["allday"] else ev["start"].strftime("%H:%M") + "  "
                d.text((130, ey-1), fit(d, t + ev["title"], font(18), W-24-130), font=font(18), fill=0)
                ey += 25; shown += 1
        if shown == 0:
            d.text((24, ey), "Nessun evento in programma", font=font(18), fill=90)
    # Quantize to 16 greys, save
    img = img.point(lambda p: (p // 16) * 17)
    img.save(out_path, "PNG", optimize=True)
    print("saved", out_path, "| weather:", "ok" if wx else wx_err, "| events:", len(events) if not ev_err else ev_err)

if __name__ == "__main__":
    render(sys.argv[1] if len(sys.argv) > 1 else str(HERE / "screen.png"))
