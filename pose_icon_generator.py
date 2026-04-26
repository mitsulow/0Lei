"""
ツキヨガ v6: 月相ポーズアイコン30枚 自動生成

各日の両手の角度に応じた人物ポーズ画像を生成する。
- 1〜15日: 南向き立ち姿（顔こちら向き・胸に「南」）
- 16〜30日: 北向き座位（背面・背中に「北」）
- 両手の開きは (lunarDay - 1) * 12 度
- 1〜15日は両手が前で動く、16〜30日は両手が後ろで動く
"""
from __future__ import annotations
import base64
import io
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
ICONS_DIR = ROOT / "pose_icons"
LOG_DIR = ROOT / "_pose_icon_logs"
ENV_FILE = Path("C:/Users/waras/hitonote-design-lp/.env.local")

FALLBACKS = ["gpt-image-2", "gpt-image-1.5", "gpt-image-1"]
BLOCKED_MODELS: set[str] = set()


def load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())


COMMON_STYLE = (
    "A single graceful Japanese woman as a minimalist ukiyo-e silhouette icon, "
    "centered on a PURE BLACK (#000000) background. "
    "She wears a flowing white kimono with subtle silvery lines. "
    "Style: ukiyo-e woodblock print silhouette, very clean, simple, app-icon style. "
    "Body and kimono drawn with delicate pale ink lines and a soft moonlit glow. "
    "Tall vertical composition, full body fits the frame from head to feet. "
    "ABSOLUTELY DO NOT INCLUDE: photorealism, anime/manga, chibi or sexy proportions, "
    "color saturation, decorative flowers, tassels, ribbons, picture frame, ground line, "
    "horizon, mountains, water, clouds, washi paper texture, multiple figures, "
    "speech bubbles, text other than the single specified kanji, scenery, complex patterns. "
    "The result must read clearly as a small standalone icon on pure black."
)


def hands_description(angle: int, mode: str) -> str:
    """両手の角度（0〜360度）と昼/夜モードからポーズ説明を生成。"""
    # angleは「両手の開きの合計」。0=合掌・上、180=水平、360=合掌・下(または背面真下)
    half = angle / 2.0
    if mode == "day":
        if angle == 0:
            return "Both arms raised straight up above her head, palms together (gassho), pointing to the sky."
        if angle <= 60:
            return f"Both arms raised high but slightly opened in a narrow V-shape, hands {half:.0f} degrees from vertical, like the start of opening a book to the sky."
        if angle <= 120:
            return f"Both arms in an open V-shape, hands lifted at about {half:.0f} degrees from vertical (so {180 - half:.0f} degrees from horizontal)."
        if angle <= 180:
            return f"Both arms stretched out wide horizontally, palms outward — like a gentle T-pose. The hands are about {half:.0f} degrees from vertical (close to horizontal at 90°)."
        # day モードは1〜15日(0〜168度)で使う想定だが念のため
        return f"Arms wide open and slightly downward, {half:.0f} degrees from vertical."
    # mode == "night"
    # angle は 180〜360 想定（座位、両手は背中側）
    if angle <= 200:
        return ("Both arms extended outward to the sides at shoulder height behind her, "
                "as if continuing the horizontal pose into the back side. Palms gently opened.")
    if angle <= 260:
        return ("Both arms drifting downward behind her back, hands now somewhere between "
                "horizontal and the lower back, palms still gently opened.")
    if angle <= 320:
        return ("Both arms drooping low behind her back, hands hanging diagonally below the seat level, "
                "fingers softly relaxed.")
    return ("Both arms fully relaxed, hanging straight down behind her back, "
            "fingertips pointing toward the ground in deep meditation.")


def build_prompt(day: int, angle: int, mode: str) -> str:
    if mode == "day":
        body = (
            "She is STANDING UPRIGHT, FACING THE VIEWER (south-facing). "
            "Her face is calm and serene, looking straight at us. "
            "On the front of her kimono, near her chest, the single kanji '南' (south) "
            "is gently inscribed in pale gold or muted red ink. "
            "Above her right hand, a small bright golden disc representing the SUN (太陽) glows softly. "
            "Above her left hand, a small pale silver crescent representing the MOON (月) glows softly."
        )
    else:
        body = (
            "She is SITTING IN MEDITATION (seiza-style or lotus-style), with her BACK TO THE VIEWER (north-facing). "
            "We see her from BEHIND — only her back, her hair, and the back of her kimono are visible. "
            "On the BACK of her kimono, the single kanji '北' (north) is gently inscribed in pale silver or muted indigo ink. "
            "Her arms reach out behind her — visible to the viewer because we see her from the back. "
            "Above her LEFT hand (which from the viewer's perspective appears on the RIGHT side), "
            "a small pale silver crescent moon (月) glows. "
            "Above her RIGHT hand (which appears on the LEFT side from us), "
            "a small bright golden sun (太陽) glows. "
            "(The sun and moon have swapped sides because we see her from the back.)"
        )
    hands = hands_description(angle, mode)
    return f"{COMMON_STYLE}\n\nFigure pose: {body}\n\nArm position: {hands}"


def generate_one(client, day: int, angle: int, mode: str, model_order: list[str]) -> dict:
    out_path = ICONS_DIR / f"pose_{day:02d}.png"
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  [SKIP] (exists) pose_{day:02d}.png", flush=True)
        return {"ok": True, "skipped": True}
    prompt = build_prompt(day, angle, mode)
    last_err = None
    for model in model_order:
        if model in BLOCKED_MODELS:
            continue
        try:
            print(f"  -> [{model}] day {day:02d} angle={angle} mode={mode} ...", flush=True)
            t0 = time.time()
            kwargs = dict(model=model, prompt=prompt, size="1024x1024", n=1)
            if model.startswith("gpt-image"):
                kwargs["quality"] = "high"
            else:
                kwargs["quality"] = "hd"
            result = client.images.generate(**kwargs)
            elapsed = time.time() - t0
            data = result.data[0]
            if hasattr(data, "b64_json") and data.b64_json:
                img_bytes = base64.b64decode(data.b64_json)
            else:
                import requests
                img_bytes = requests.get(data.url, timeout=60).content
            from PIL import Image
            img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
            img_resized = img.resize((256, 256), Image.LANCZOS)
            ICONS_DIR.mkdir(parents=True, exist_ok=True)
            img_resized.save(out_path, "PNG", optimize=True, compress_level=9)
            kb = out_path.stat().st_size / 1024
            print(f"  [OK]  saved pose_{day:02d}.png ({kb:,.0f} KB, {elapsed:,.1f}s, {model})", flush=True)
            return {"ok": True, "model": model}
        except Exception as e:
            last_err = e
            msg = str(e)
            print(f"  [NG]  {model} failed: {msg[:200]}", flush=True)
            msg_low = msg.lower()
            if any(kw in msg_low for kw in ["must be verified", "403", "not found", "does not exist", "access denied"]):
                BLOCKED_MODELS.add(model)
                continue
            if "invalid size" in msg_low or "unsupported" in msg_low:
                continue
            break
    return {"ok": False, "error": str(last_err)}


def main():
    load_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY not set", flush=True)
        sys.exit(1)
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    model_order = list(FALLBACKS)

    # 引数: "test" = 1日のみ / "priority" = 1, 7, 15, 23 / "all" = 30枚 / 数字 = 単独
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg == "test":
        days = [1]
    elif arg == "priority":
        days = [1, 7, 15, 23]
    elif arg.isdigit():
        days = [int(arg)]
    else:
        days = list(range(1, 31))

    print(f"Targets: {days}", flush=True)
    t_start = time.time()
    results = []
    for i, d in enumerate(days, 1):
        angle = (d - 1) * 12
        mode = "day" if d <= 15 else "night"
        print(f"[{i}/{len(days)}] day={d:02d} angle={angle} mode={mode}", flush=True)
        res = generate_one(client, d, angle, mode, model_order)
        results.append({"day": d, "angle": angle, "mode": mode, **res})
    elapsed = time.time() - t_start

    import json
    log_path = LOG_DIR / f"run-{int(time.time())}.json"
    log_path.write_text(json.dumps({"results": results, "elapsed_sec": elapsed}, ensure_ascii=False, indent=2), encoding="utf-8")

    ok = sum(1 for r in results if r.get("ok"))
    ng = len(results) - ok
    print("=" * 50)
    print(f"DONE: ok={ok} ng={ng} total={len(results)} elapsed={elapsed:,.1f}s")
    if ng:
        sys.exit(2)


if __name__ == "__main__":
    main()
