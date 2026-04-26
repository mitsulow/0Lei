"""
ツキヨガ v6: 浮世絵風 月の満ち欠けアイコン30枚 自動生成スクリプト

- gpt-image-2 → gpt-image-1.5 → gpt-image-1 の順にフォールバック
- 1024x1024で生成 → 512x512 にリサイズして PNG 保存
- 既存ファイルはスキップ（レジューム可能）
- 完全自動（プロンプト確認なし）
"""
from __future__ import annotations
import base64
import io
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
ICONS_DIR = ROOT / "moon_icons"
LOG_DIR = ROOT / "_moon_icon_logs"
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


MOON_SPECS = [
    {"day": 1,  "name": "ツキタチ",       "phase": "new_moon",        "lit_pct": 0,   "priority": True},
    {"day": 2,  "name": "フツカヅキ",     "phase": "waxing_crescent", "lit_pct": 4},
    {"day": 3,  "name": "ミカヅキ",       "phase": "waxing_crescent", "lit_pct": 12},
    {"day": 4,  "name": "マユヅキ",       "phase": "waxing_crescent", "lit_pct": 22},
    {"day": 5,  "name": "ユウヅキ",       "phase": "waxing_crescent", "lit_pct": 33},
    {"day": 6,  "name": "ムイカヅキ",     "phase": "waxing_crescent", "lit_pct": 42},
    {"day": 7,  "name": "カタミニ",       "phase": "first_quarter",   "lit_pct": 50,  "priority": True},
    {"day": 8,  "name": "ヨイヅキ",       "phase": "waxing_gibbous",  "lit_pct": 58},
    {"day": 9,  "name": "ココノカヅキ",   "phase": "waxing_gibbous",  "lit_pct": 66},
    {"day": 10, "name": "トカンヤ",       "phase": "waxing_gibbous",  "lit_pct": 74},
    {"day": 11, "name": "ジュウイチヤ",   "phase": "waxing_gibbous",  "lit_pct": 81},
    {"day": 12, "name": "ジュウニヤ",     "phase": "waxing_gibbous",  "lit_pct": 87},
    {"day": 13, "name": "アタラヨ",       "phase": "waxing_gibbous",  "lit_pct": 93,  "priority": True, "special": "tsukinukurushasa-tooka-mikka"},
    {"day": 14, "name": "マチヨイ",       "phase": "waxing_gibbous",  "lit_pct": 97},
    {"day": 15, "name": "クマナシ",       "phase": "full_moon",       "lit_pct": 100, "priority": True},
    {"day": 16, "name": "イザヨイ",       "phase": "waning_gibbous",  "lit_pct": 97},
    {"day": 17, "name": "タチマチ",       "phase": "waning_gibbous",  "lit_pct": 93},
    {"day": 18, "name": "イマチ",         "phase": "waning_gibbous",  "lit_pct": 87},
    {"day": 19, "name": "ネマチ",         "phase": "waning_gibbous",  "lit_pct": 81},
    {"day": 20, "name": "フケマチ",       "phase": "waning_gibbous",  "lit_pct": 74},
    {"day": 21, "name": "ニジュウイチヤ", "phase": "waning_gibbous",  "lit_pct": 66},
    {"day": 22, "name": "ニジュウニヤ",   "phase": "waning_gibbous",  "lit_pct": 58},
    {"day": 23, "name": "アリアケ",       "phase": "last_quarter",    "lit_pct": 50,  "priority": True},
    {"day": 24, "name": "ニジュウヨヤ",   "phase": "waning_crescent", "lit_pct": 42},
    {"day": 25, "name": "ホシアヒ",       "phase": "waning_crescent", "lit_pct": 33},
    {"day": 26, "name": "ナゴリヅキ",     "phase": "waning_crescent", "lit_pct": 22},
    {"day": 27, "name": "アカツキ",       "phase": "waning_crescent", "lit_pct": 12},
    {"day": 28, "name": "アケボノ",       "phase": "waning_crescent", "lit_pct": 4},
    {"day": 29, "name": "ツゴモリ",       "phase": "old_moon",        "lit_pct": 1},
    {"day": 30, "name": "ミソカ",         "phase": "new_moon",        "lit_pct": 0},
]

COMMON_STYLE = (
    "A single moon disc rendered as a clean circular icon, centered on a PURE BLACK (#000000) background. "
    "The moon is drawn in the spirit of Tsukioka Yoshitoshi's 'One Hundred Aspects of the Moon' (Tsuki Hyakushi) — "
    "but ONLY the moon itself, isolated, like an app icon. "
    "The moon is a perfect circle, filling about 88% of the image width, perfectly centered. "
    "Lit surface: pale silvery-gold moonlight with subtle warm tone, soft luminous quality. "
    "Shadow side of the moon: PURE BLACK, completely flat, identical to the surrounding background, "
    "so the dark portion of the moon disappears seamlessly into the background. "
    "A delicate silhouette of the rabbit pounding mochi (Japanese tradition of the lunar rabbit) "
    "is faintly etched INSIDE the LIT portion of the moon only — never on the shadow side, never outside the disc. "
    "ABSOLUTELY DO NOT INCLUDE: washi paper texture, paper grain, parchment, torn edges, "
    "ink-wash bleed outside the moon, sumi-bokashi gradient outside the disc, mist or halo extending beyond the moon, "
    "any shadow on the ground beneath the moon, ground line, horizon, landscape, clouds, stars, mountains, trees, water, "
    "red signature stamp (hanko / raku-kan), Japanese characters, calligraphy, picture frame, decorative border, "
    "indigo or blue tint in the shadow side (the shadow must be PURE BLACK, not indigo), "
    "photorealism, NASA imagery, anime/manga style, western astrology signs, moon-with-a-face, cartoon faces. "
    "The output must look like a clean app icon: ONLY the lit portion of the moon glowing on a flat black background, "
    "with the rabbit silhouette gently visible inside the lit area."
)


def phase_description(spec: dict) -> str:
    phase = spec["phase"]
    pct = spec.get("lit_pct", 0)
    if phase == "new_moon":
        if pct == 0 and spec["day"] == 1:
            return ("New moon (Tsukitachi). Almost the entire disc is PURE BLACK and disappears into the background. "
                    "Only the very thinnest sliver of pale moonlight is faintly visible at the right edge, like a hair-line of light. "
                    "Otherwise, complete darkness.")
        return ("Dark moon (Misoka). The disc is essentially PURE BLACK and disappears into the background. "
                "Only the faintest whisper of light at the LEFT edge, almost invisible.")
    if phase == "first_quarter":
        return ("First quarter half-moon (Katamini). The RIGHT half of the moon is fully illuminated with pale silvery-gold moonlight. "
                "The LEFT half is PURE BLACK and completely invisible (it merges into the black background). "
                "Sharp clean terminator down the center. Faint rabbit-mochi silhouette visible inside the lit right half.")
    if phase == "full_moon":
        return ("Full moon (Kumanashi - 'no shadows'). A perfect glowing disc, fully and evenly illuminated. "
                "Faint rabbit-mochi-pounding silhouette visible across the lit surface. "
                "The disc has a subtle inner luminance — but NO halo or glow extends beyond the disc into the background.")
    if phase == "last_quarter":
        return ("Last quarter half-moon (Ariake). The LEFT half of the moon is fully illuminated. "
                "The RIGHT half is PURE BLACK and completely invisible (merges into the black background). "
                "Mirror image of the first quarter. Faint rabbit-mochi silhouette inside the lit left half.")
    if phase == "waxing_crescent":
        return (f"Waxing crescent moon, with only the RIGHT side illuminated — about {pct}% of the disc is lit. "
                f"Crescent opens to the LEFT, the bright sliver hugs the right edge. "
                f"The unlit portion is PURE BLACK and DISAPPEARS completely into the black background — it must NOT be visible at all.")
    if phase == "waxing_gibbous":
        return (f"Waxing gibbous moon, RIGHT side dominantly illuminated — about {pct}% of the disc is lit. "
                f"Only a thin crescent of darkness on the LEFT edge — that dark portion is PURE BLACK and invisible against the background. "
                f"Faint rabbit-mochi inside the lit area.")
    if phase == "waning_gibbous":
        return (f"Waning gibbous moon, LEFT side dominantly illuminated — about {pct}% of the disc is lit. "
                f"Only a thin crescent of darkness on the RIGHT edge — PURE BLACK, invisible against the background. "
                f"Faint rabbit-mochi inside the lit area.")
    if phase == "waning_crescent":
        return (f"Waning crescent moon, only the LEFT side illuminated — about {pct}% of the disc is lit. "
                f"Crescent opens to the RIGHT, the bright sliver hugs the left edge. "
                f"The unlit portion is PURE BLACK and disappears completely into the background.")
    if phase == "old_moon":
        return ("Old moon (Tsugomori, 'month-hidden'). The entire disc is PURE BLACK and vanishes into the background. "
                "Only a hair-line sliver of pale light at the LEFT edge remains visible.")
    return ""


def build_prompt(spec: dict) -> str:
    desc = phase_description(spec)
    special = ""
    if spec.get("special") == "tsukinukurushasa-tooka-mikka":
        special = (" Special note: this is 'Atarayo', the moon of the 13th lunar day — slightly warmer gold tone in the lit area, "
                   "but still ONLY the moon disc, no decoration outside the disc.")
    return f"{COMMON_STYLE}\n\nMoon phase: {desc}{special}"


def generate_one(client, spec: dict, model_order: list[str]) -> dict:
    out_path = ICONS_DIR / f"moon_{spec['day']:02d}.png"
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  [SKIP] (exists) moon_{spec['day']:02d}.png", flush=True)
        return {"ok": True, "skipped": True}
    prompt = build_prompt(spec)
    last_err = None
    for model in model_order:
        if model in BLOCKED_MODELS:
            continue
        try:
            print(f"  -> [{model}] generating day {spec['day']:02d} ({spec['name']}) ...", flush=True)
            t0 = time.time()
            kwargs = dict(
                model=model,
                prompt=prompt,
                size="1024x1024",
                n=1,
            )
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
            img_resized = img.resize((512, 512), Image.LANCZOS)
            ICONS_DIR.mkdir(parents=True, exist_ok=True)
            img_resized.save(out_path, "PNG", optimize=True)
            kb = out_path.stat().st_size / 1024
            print(f"  [OK]  saved moon_{spec['day']:02d}.png ({kb:,.0f} KB, {elapsed:,.1f}s, {model})", flush=True)
            return {"ok": True, "model": model, "elapsed": elapsed}
        except Exception as e:
            last_err = e
            msg = str(e)
            print(f"  [NG]  {model} failed: {msg[:200]}", flush=True)
            msg_low = msg.lower()
            if any(kw in msg_low for kw in ["must be verified", "403", "not found", "does not exist", "access denied", "model_not_found"]):
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
    print(f"Model order: {model_order}", flush=True)
    print(f"Output dir : {ICONS_DIR}", flush=True)
    print()

    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode == "priority":
        targets = [s for s in MOON_SPECS if s.get("priority")]
    elif mode == "rest":
        targets = [s for s in MOON_SPECS if not s.get("priority")]
    else:
        targets = MOON_SPECS

    print(f"Targets: {len(targets)} icons", flush=True)
    print()

    t_start = time.time()
    results = []
    for i, spec in enumerate(targets, 1):
        print(f"[{i}/{len(targets)}] day {spec['day']:02d} {spec['name']}", flush=True)
        res = generate_one(client, spec, model_order)
        results.append({"day": spec["day"], "name": spec["name"], **res})
        print()

    elapsed = time.time() - t_start
    ok = sum(1 for r in results if r.get("ok"))
    ng = len(results) - ok

    import json
    log_path = LOG_DIR / f"run-{int(time.time())}.json"
    log_path.write_text(json.dumps({"results": results, "elapsed_sec": elapsed}, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 50)
    print(f"DONE: ok={ok} ng={ng} total={len(results)} elapsed={elapsed:,.1f}s", flush=True)
    print(f"Log : {log_path}", flush=True)
    if ng:
        sys.exit(2)


if __name__ == "__main__":
    main()
