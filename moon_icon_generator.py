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
    "Traditional Japanese ukiyo-e woodblock print of the moon. "
    "Style heavily inspired by Tsukioka Yoshitoshi's 'One Hundred Aspects of the Moon' (Tsuki Hyakushi) series, "
    "with influences from Hokusai and Hiroshige. "
    "The moon is centered, occupying about 75% of the image width, on a transparent or near-black indigo background. "
    "Color palette: lit surface in pale gold and silvery white moonlight; shadow side in deep indigo (ai) and sumi-ink black; "
    "soft sumi-bokashi gradient at the terminator (light/shadow boundary) like ink wash bleed on washi paper. "
    "Subtle washi paper texture overlay. Faint rabbit-mochi-pounding pattern (the Japanese tradition where the lunar maria "
    "appear as a rabbit pounding mochi) etched delicately into the lit surface, never dominant. "
    "Serene, profound, wabi-sabi aesthetic. Quiet, contemplative, unworldly. "
    "STRICTLY AVOID: photorealistic style, NASA-style realism, anime/manga style, "
    "western astrology symbols, zodiac signs, moon-with-a-face, cartoon faces, neon colors, glitter effects."
)


def phase_description(spec: dict) -> str:
    phase = spec["phase"]
    pct = spec.get("lit_pct", 0)
    if phase == "new_moon":
        if pct == 0 and spec["day"] == 1:
            return ("New moon (Tsukitachi). The moon is almost entirely in shadow; only a faint silhouette of the lunar disc "
                    "is visible against the deep night, ringed by a subtle corona of pale moonlight. "
                    "Mysterious, the very beginning of the lunar cycle.")
        return ("Dark moon at the very end of the cycle (Misoka). The lunar disc is essentially in shadow, "
                "a barely perceptible whisper of light, on the verge of disappearing into the new moon.")
    if phase == "first_quarter":
        return ("First quarter half-moon (Katamini). The right half of the moon is fully illuminated with pale gold-silver light, "
                "the left half in deep indigo shadow. The terminator line down the center is a soft, slightly bleeding sumi-ink wash. "
                "Faint rabbit-mochi pattern visible on the lit half.")
    if phase == "full_moon":
        return ("Full moon (Kumanashi - 'no shadows'). A perfect luminous disc, fully and evenly illuminated, "
                "no terminator at all. Soft glowing aureole bleeds outward into the night sky. "
                "Faint rabbit-mochi-pounding silhouette visible across the surface. The classic 'chushu no meigetsu' (mid-autumn moon) of ukiyo-e.")
    if phase == "last_quarter":
        return ("Last quarter half-moon (Ariake). The LEFT half of the moon is fully illuminated, the RIGHT half in deep indigo shadow. "
                "Mirror image of the first quarter. The melancholy moon lingering in the dawn sky.")
    if phase == "waxing_crescent":
        return (f"Waxing crescent moon, with the RIGHT side illuminated at approximately {pct}% of the disc. "
                f"Crescent opening to the LEFT, with the bright sliver on the right edge. "
                f"The shadow side is deep indigo with a faint silhouette of the dark portion.")
    if phase == "waxing_gibbous":
        return (f"Waxing gibbous moon, with the RIGHT side dominantly illuminated at approximately {pct}% of the disc. "
                f"Shadow on the LEFT edge only. Soft sumi-bokashi terminator on the left side.")
    if phase == "waning_gibbous":
        return (f"Waning gibbous moon, with the LEFT side dominantly illuminated at approximately {pct}% of the disc. "
                f"Shadow on the RIGHT edge only. Mirror of waxing gibbous.")
    if phase == "waning_crescent":
        return (f"Waning crescent moon, with the LEFT side illuminated at approximately {pct}% of the disc. "
                f"Crescent opening to the RIGHT, with the bright sliver on the left edge.")
    if phase == "old_moon":
        return ("Old moon (Tsugomori, 'month-hidden'). Almost entirely dark, with only the faintest sliver of light "
                "on the LEFT edge, on the verge of vanishing.")
    return ""


def build_prompt(spec: dict) -> str:
    desc = phase_description(spec)
    special = ""
    if spec.get("special") == "tsukinukurushasa-tooka-mikka":
        special = (" Special: this is 'Atarayo', evoking the Okinawan folk song 'Tsuki nu kaisha juu nu mikka' "
                   "(the moon is most beautiful on the 13th); add the most delicate gold-leaf shimmer.")
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
