"""
ツキヨガ v6 ── ポーズ画像 v2（改良版）

変更点（v1からの修正）:
- 太陽と月は「常に空（昼）or 足元（夜）」に固定（両手と分離）
- 両手の角度は「両手の隙間角度」として厳密化（0=合掌, 180=水平）
- 1〜15日と16〜30日で角度パターンが対称（90度→180度→90度→0度）
- 白背景生成→PILで透明化する前提
- 特別2枚は省略
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
LOG_DIR = ROOT / "_pose_v2_logs"
ENV_FILE = Path("C:/Users/waras/hitonote-design-lp/.env.local")

FALLBACKS = ["gpt-image-1.5", "gpt-image-1"]
BLOCKED_MODELS: set[str] = set()

# 角度テーブル（ユーザー承認版）
ANGLES = {
    1: 0, 2: 15, 3: 30, 4: 45, 5: 60, 6: 75, 7: 90, 8: 100, 9: 115, 10: 125,
    11: 135, 12: 145, 13: 160, 14: 170, 15: 180,
    16: 170, 17: 155, 18: 145, 19: 135, 20: 125, 21: 110, 22: 100, 23: 90,
    24: 75, 25: 65, 26: 50, 27: 40, 28: 25, 29: 15, 30: 0,
}

NAMES = {
    1: "tsukitachi", 2: "futsukazuki", 3: "mikazuki", 4: "mayuzuki",
    5: "yuzuki", 6: "muikazuki", 7: "katamini", 8: "yoizuki",
    9: "kokonokazuki", 10: "tokanya", 11: "juuichiya", 12: "juuniya",
    13: "atarayo", 14: "machiyoi", 15: "kumanashi", 16: "izayoi",
    17: "tachimachi", 18: "imachi", 19: "nemachi", 20: "fukemachi",
    21: "nijuuichiya", 22: "nijuuniya", 23: "ariake", 24: "nijuuyoya",
    25: "hoshiai", 26: "nagorizuki", 27: "akatsuki", 28: "akebono",
    29: "tsugomori", 30: "misoka",
}

# 月相の英語記述（昼/夜共通）
MOON_PHASES = {
    1: "NEW MOON: sun and moon completely overlap into a single golden orb with a faint silver halo (conjunction).",
    2: "Extremely thin waxing crescent moon, barely visible silver sliver on the right edge.",
    3: "Thin waxing crescent moon (right side lit).",
    4: "Eyebrow-shaped waxing crescent moon (right side).",
    5: "Waxing crescent, about 1/4 illuminated on the right.",
    6: "Waxing crescent, about 1/3 illuminated on the right.",
    7: "FIRST QUARTER half-moon, right side perfectly illuminated, left side in shadow.",
    8: "Waxing gibbous moon, more than half illuminated on the right.",
    9: "Waxing gibbous, about 2/3 illuminated.",
    10: "Large waxing gibbous, almost 3/4 illuminated.",
    11: "Near-full waxing gibbous moon.",
    12: "Almost full waxing moon.",
    13: "Just before full moon (atarayo eve), with a delicate gold-warm tint.",
    14: "Nearly full moon, very subtle shadow on the lower-left.",
    15: "FULL MOON: a perfect bright silver-white circular disc, fully illuminated.",
    16: "Just past full, beginning to wane on the lower-left edge.",
    17: "Waning gibbous moon, lit on the right.",
    18: "Waning gibbous moon.",
    19: "Smaller waning gibbous moon.",
    20: "Less than gibbous, waning.",
    21: "Between half and gibbous, waning, lit on the right.",
    22: "Almost half waning moon.",
    23: "LAST QUARTER half-moon, LEFT side perfectly illuminated (mirror of first quarter).",
    24: "Waning crescent, about 1/3 illuminated on the left.",
    25: "Waning crescent, about 1/4 lit on the left.",
    26: "Thin waning crescent.",
    27: "Very thin waning crescent.",
    28: "Mere sliver waning crescent.",
    29: "Almost hidden, only a hair-line of light remaining.",
    30: "DARK MOON / new moon: sun and moon merged into one golden-silver orb again (conjunction returns).",
}


COMMON = (
    "Photorealistic full-body portrait of a graceful Japanese woman in her early 30s. "
    "Slim, serene yoga practitioner. Black hair tied in a high bun (top knot). "
    "Calm meditative expression. Wearing a deep purple yoga outfit "
    "(purple racerback yoga top + matching purple high-waisted yoga leggings), bare feet. "
    "Lighting: soft, even, natural studio light. "
    "Background: PURE WHITE (#FFFFFF), completely empty, no walls, no floor, no shadows on the ground. "
    "The figure stands isolated against pure white, ready for cutout. "
    "Composition: full body visible from head to toe, vertical portrait orientation, figure centered."
)

HIRU_EXTRA = (
    "Direction: Standing FRONT-FACING the camera (south-facing). Face and body turned toward the viewer. "
    "Body upright on both feet, weight evenly balanced. "
    "On her lower abdomen (belly area): a single clear large Japanese kanji '南' (south) in elegant gold calligraphy. "
    "Celestial bodies (FIXED, do not move with the hands): "
    "the SUN (golden glowing orb) appears in the upper-right of the sky region above her head; "
    "the MOON appears in the upper-left of the sky region. "
    "Both are clearly drawn in the upper portion of the image, NOT in her hands."
)

YORU_EXTRA = (
    "Direction: Standing with her BACK TO THE CAMERA (back-view, north-facing). We see her from behind. "
    "Body upright on both feet. "
    "On her upper back: a single clear large Japanese kanji '北' (north) in elegant gold calligraphy. "
    "Celestial bodies (FIXED, do not move with the hands): "
    "the SUN (golden glowing orb) appears at the lower-LEFT of the image, near her feet (mirrored because we view from behind); "
    "the MOON appears at the lower-RIGHT of the image, near her feet. "
    "Both are clearly at the bottom of the image, representing the night-side underground celestial position."
)


def pose_description(angle: int, mode: str) -> str:
    if mode == "hiru":
        # 両手は基本「上方向」、隙間角度に応じて開く
        if angle == 0:
            return ("Pose: Both arms raised STRAIGHT UP overhead, palms pressed together in prayer (gassho). "
                    "Hands meeting at the apex above her crown. Arms parallel and forming a single vertical line. No gap between them.")
        if angle == 180:
            return ("Pose: Both arms FULLY EXTENDED HORIZONTALLY to the sides at shoulder height (T-pose). "
                    "Arms parallel to the ground, palms facing forward, fingers extended. "
                    "180° between the two arms (a perfect horizontal line through the shoulders).")
        half = angle / 2.0
        return (f"Pose: Both arms raised symmetrically in a V-shape ABOVE her head, with a {angle}° angular gap between the arms. "
                f"Each arm is tilted {half:.0f}° OUTWARD from the vertical-upward direction. "
                f"Right arm points up-and-right, left arm points up-and-left. "
                f"Hands open, palms forward, fingers extended.")
    # yoru: 両手は基本「下方向」、隙間角度に応じて開く（両手はバックビューで見える）
    if angle == 0:
        return ("Pose: Both arms straight DOWN at her sides ('kiotsuke' attention posture), hands relaxed beside the thighs. "
                "Arms parallel and forming a single vertical line down. No gap between them. Body completely vertical.")
    if angle == 180:
        return ("Pose: Both arms EXTENDED HORIZONTALLY to the sides at shoulder height, like wings spread from behind. "
                "Arms parallel to the ground, palms relaxed. 180° between the two arms (T-pose seen from the back).")
    half = angle / 2.0
    return (f"Pose: Both arms in a symmetric DOWNWARD V-shape, with a {angle}° angular gap between the arms. "
            f"Each arm is tilted {half:.0f}° OUTWARD from the vertical-downward direction. "
            f"Right arm points down-and-right, left arm points down-and-left (as seen from behind). "
            f"Hands relaxed, palms slightly inward.")


def build_prompt(mode: str, day: int) -> str:
    angle = ANGLES[day]
    extra = HIRU_EXTRA if mode == "hiru" else YORU_EXTRA
    pose = pose_description(angle, mode)
    moon = f"Moon phase: {MOON_PHASES[day]}"
    return f"{COMMON}\n\n{extra}\n\n{pose}\n\n{moon}"


def load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())


def generate_one(client, mode: str, day: int, model_order: list[str]) -> dict:
    out_path = ICONS_DIR / f"{mode}_{day:02d}.png"
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  [SKIP] {out_path.name}", flush=True)
        return {"ok": True, "skipped": True}
    prompt = build_prompt(mode, day)
    last_err = None
    for model in model_order:
        if model in BLOCKED_MODELS:
            continue
        try:
            print(f"  -> [{model}] {mode} {day:02d} ang={ANGLES[day]} ...", flush=True)
            t0 = time.time()
            kwargs = dict(model=model, prompt=prompt, n=1, size="1024x1536", quality="high")
            result = client.images.generate(**kwargs)
            elapsed = time.time() - t0
            data = result.data[0]
            if hasattr(data, "b64_json") and data.b64_json:
                img_bytes = base64.b64decode(data.b64_json)
            else:
                import requests
                img_bytes = requests.get(data.url, timeout=60).content
            ICONS_DIR.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(img_bytes)
            kb = out_path.stat().st_size / 1024
            print(f"  [OK]  {out_path.name} ({kb:,.0f} KB, {elapsed:,.1f}s, {model})", flush=True)
            return {"ok": True, "model": model}
        except Exception as e:
            last_err = e
            msg = str(e)
            print(f"  [NG]  {model} failed: {msg[:200]}", flush=True)
            msg_low = msg.lower()
            if any(kw in msg_low for kw in ["must be verified", "403", "not found", "does not exist", "access denied", "model_not_found"]):
                BLOCKED_MODELS.add(model)
                continue
            if "content_policy" in msg_low or "content filters" in msg_low:
                continue
            if "invalid size" in msg_low or "unsupported" in msg_low or "billing" in msg_low:
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

    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg == "priority":
        targets = []
        for d in [1, 7, 15, 23]:
            targets.append(("hiru", d))
            targets.append(("yoru", d))
    elif arg == "all":
        targets = []
        for d in range(1, 31):
            targets.append(("hiru", d))
        for d in range(1, 31):
            targets.append(("yoru", d))
    else:
        print(f"unknown arg: {arg}")
        sys.exit(2)

    model_order = list(FALLBACKS)
    print(f"Model order: {model_order}", flush=True)
    print(f"Targets: {len(targets)}", flush=True)

    t_start = time.time()
    results = []
    for i, (mode, day) in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] {mode} {day:02d}", flush=True)
        res = generate_one(client, mode, day, model_order)
        results.append({"mode": mode, "day": day, **res})

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
