#!/usr/bin/env python3
"""
Schumann Resonance Fetcher for GitHub Actions
Downloads srf.jpg from Tomsk State University → pixel analysis → schumann.json
"""
import json, os, sys, datetime, urllib.request
from io import BytesIO
from PIL import Image

TOMSK_URL = "https://sos70.ru/provider.php?file=srf.jpg"
OUTPUT = "schumann.json"
HISTORY = "schumann_history.json"
MAX_HISTORY = 8640  # 30 days × 288 per day (5min intervals)

def fetch():
    req = urllib.request.Request(TOMSK_URL, headers={
        "User-Agent": "Mozilla/5.0 SchumannMonitor/1.0",
        "Cache-Control": "no-cache"
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    print(f"Downloaded {len(data)} bytes")
    return Image.open(BytesIO(data)).convert("RGB")

def analyze(img):
    w, h = img.size
    px = img.load()
    print(f"Image: {w}x{h}")

    # Plot boundaries
    pL, pR = int(w*0.08), int(w*0.95)
    for x in range(int(w*0.03), int(w*0.15)):
        dk = sum(1 for y in range(int(h*0.1), int(h*0.4), 3) if all(c < 40 for c in px[x,y]))
        if dk > 15: pL = x; break
    for x in range(w - int(w*0.02), int(w*0.8), -1):
        dk = sum(1 for y in range(int(h*0.1), int(h*0.4), 3) if all(c < 40 for c in px[x,y]))
        if dk > 15: pR = x; break

    # F1 grid calibration
    f1T, f1B = int(h*0.06), int(h*0.44)
    gRows = []
    for y in range(int(h*0.03), int(h*0.50)):
        lp = sum(1 for x in range(pL+10, pL+int((pR-pL)*0.3), 4)
                 if all(30 < c < 140 for c in px[x,y]))
        if lp > 20: gRows.append(y)

    if gRows:
        gLines, cl = [], [gRows[0]]
        for i in range(1, len(gRows)):
            if gRows[i] - gRows[i-1] <= 4: cl.append(gRows[i])
            else: gLines.append(round(sum(cl)/len(cl))); cl = [gRows[i]]
        gLines.append(round(sum(cl)/len(cl)))
        if len(gLines) >= 5:
            sp = gLines[1] - gLines[0]
            f1L = [gLines[0]]
            for i in range(1, len(gLines)):
                if gLines[i] - gLines[i-1] < sp*2.5: f1L.append(gLines[i])
                else: break
            if len(f1L) >= 4: f1T, f1B = f1L[0], f1L[-1]

    # Mode definitions
    def is_white(r,g,b): return r>190 and g>190 and b>190 and max(abs(r-g),abs(r-b),abs(g-b))<55
    def is_yellow(r,g,b): return r>150 and g>130 and b<110 and r>b*1.6 and g>b*1.3
    def is_red(r,g,b): return r>100 and g<90 and b<90 and r>g*1.4 and r>b*1.4
    def is_green(r,g,b): return g>80 and r<100 and b<100 and g>r*1.15 and g>b*1.15

    modes = [
        {"name":"f1", "yTop":f1T, "yBot":f1B, "hzTop":8.30, "hzBot":7.20, "match":is_white},
        {"name":"f2", "yTop":f1T, "yBot":f1B, "hzTop":14.40, "hzBot":13.00, "match":is_yellow},
        {"name":"f3", "yTop":int(h*0.42), "yBot":int(h*0.72), "hzTop":21.10, "hzBot":18.30, "match":is_red},
        {"name":"f4", "yTop":int(h*0.60), "yBot":int(h*0.95), "hzTop":26.90, "hzBot":24.00, "match":is_green},
    ]

    pw = pR - pL

    # Adaptive scan (v7 proven logic)
    scan_zones = [
        ("latest(85-92%)", 0.85, 0.92),
        ("recent(75-85%)", 0.75, 0.85),
        ("6h(65-75%)", 0.65, 0.75),
        ("12h(50-65%)", 0.50, 0.65),
    ]

    best = None
    for label, s, e in scan_zones:
        xs, xe = int(pL + pw*s), int(pL + pw*e)
        hits = 0
        for x in range(xs, xe+1, 3):
            for y in range(f1T, f1B, 2):
                if is_white(*px[x,y]): hits += 1
            if hits >= 3: break
        print(f"  Zone {label}: {hits}")
        if hits >= 3: best = (label, s, e); break

    if not best:
        print("  All zones empty, fallback to 65-75%")
        best = ("fallback(65-75%)", 0.65, 0.75)

    label, s, e = best
    xs, xe = int(pL + pw*s), int(pL + pw*e)
    print(f"  ✓ {label} x[{xs}..{xe}]")

    results = {}
    for mode in modes:
        mH = mode["yBot"] - mode["yTop"]
        if mH <= 0: results[mode["name"]] = None; continue
        def y_to_hz(y): return mode["hzTop"] - ((y - mode["yTop"]) / mH) * (mode["hzTop"] - mode["hzBot"])

        vals = []
        for x in range(xs, xe+1):
            col_y = [y for y in range(mode["yTop"], mode["yBot"]) if mode["match"](*px[x,y])]
            if col_y:
                col_y.sort()
                hz = y_to_hz(col_y[len(col_y)//2])
                if mode["hzBot"]-1 <= hz <= mode["hzTop"]+1:
                    vals.append(hz)

        if len(vals) >= 2:
            vals.sort()
            med = vals[len(vals)//2]
            results[mode["name"]] = round(med, 2)
            print(f"  ★ {mode['name']}: {med:.2f} Hz ({len(vals)} pts)")
        else:
            results[mode["name"]] = None
            print(f"  {mode['name']}: insufficient ({len(vals)})")

    # 24h average (F1 only)
    d3S, d3E = int(pL + pw*0.10), xe
    avg24 = None
    day_vals = []
    m1 = modes[0]
    m1H = m1["yBot"] - m1["yTop"]
    for x in range(d3S, d3E+1, 4):
        col_y = [y for y in range(m1["yTop"], m1["yBot"]) if is_white(*px[x,y])]
        if col_y:
            col_y.sort()
            hz = m1["hzTop"] - ((col_y[len(col_y)//2] - m1["yTop"]) / m1H) * (m1["hzTop"] - m1["hzBot"])
            if 6.5 <= hz <= 9.5: day_vals.append(hz)

    if len(day_vals) >= 10:
        mn = sum(day_vals) / len(day_vals)
        sd = (sum((v-mn)**2 for v in day_vals) / len(day_vals)) ** 0.5
        flt = [v for v in day_vals if abs(v-mn) < sd*2]
        avg24 = round(sum(flt) / len(flt), 2)
        print(f"  ★ 24h avg: {avg24} Hz ({len(flt)} pts)")

    return results, avg24, len(day_vals), label

def main():
    print("=== Schumann Fetcher ===")
    img = fetch()
    modes, avg24, day_pts, zone = analyze(img)

    now = datetime.datetime.utcnow().isoformat() + "Z"

    # Current data
    current = {
        "timestamp": now,
        "zone": zone,
        "modes": modes,
        "avg24": avg24,
        "avg24_points": day_pts,
    }

    with open(OUTPUT, "w") as f:
        json.dump(current, f, indent=2)
    print(f"Wrote {OUTPUT}")

    # Append to history
    history = []
    if os.path.exists(HISTORY):
        try:
            with open(HISTORY) as f:
                history = json.load(f)
        except: pass

    history.append({
        "t": now,
        "f1": modes.get("f1"),
        "f2": modes.get("f2"),
        "f3": modes.get("f3"),
        "f4": modes.get("f4"),
    })

    # Trim to max
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    with open(HISTORY, "w") as f:
        json.dump(history, f)
    print(f"History: {len(history)} records")

if __name__ == "__main__":
    main()
