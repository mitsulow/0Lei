# -*- coding: utf-8 -*-
"""
Blitzortung の落雷ストリームに60秒だけ接続して「1分あたりの世界の雷検知数」を採る。
毎時のcronで積み上げ → history/lightning.json（[UTC ISO, 発/分] の配列・最大 ~1年分）。
失敗しても外側のワークフローを落とさない（その回はスキップ）。
"""
import asyncio
import json
import os
from datetime import datetime, timezone

HIST = os.path.join("history", "lightning.json")
KEEP = 4 * 24 * 400  # 15分ごと1点 × 400日ぶん(外部cron-job.orgの15分キックに同乗)


async def count(seconds: int = 60) -> int:
    import websockets

    n = 0
    for host in ("wss://ws1.blitzortung.org/", "wss://ws7.blitzortung.org/", "wss://ws8.blitzortung.org/"):
        try:
            async with websockets.connect(host, open_timeout=10) as ws:
                await ws.send(json.dumps({"a": 111}))
                loop = asyncio.get_event_loop()
                end = loop.time() + seconds
                while loop.time() < end:
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=max(0.1, end - loop.time()))
                        n += 1
                    except asyncio.TimeoutError:
                        break
            return n
        except Exception as e:  # 次のホストへ
            print("ws fail:", host, e)
            n = 0
    return -1


def main():
    n = asyncio.run(count(60))
    if n < 0:
        print("lightning: all hosts failed — skip")
        return
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    hist = []
    try:
        with open(HIST, encoding="utf-8") as f:
            hist = json.load(f)
    except Exception:
        pass
    hist.append([ts, n])
    hist = hist[-KEEP:]
    os.makedirs("history", exist_ok=True)
    with open(HIST, "w", encoding="utf-8") as f:
        json.dump(hist, f, separators=(",", ":"))
    print(f"lightning: {n} strikes/min @ {ts} (total {len(hist)} samples)")


if __name__ == "__main__":
    main()
