"""
ツキヨガ 採用案フォルダの不足14日分を gpt-image-1.5 で生成する。
スタイル: 緑バック、紫ヨガコスチューム女性、既存採用案と同じ雰囲気。
"""
from __future__ import annotations
import base64
import io
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
DST = Path(r"C:\Users\waras\OneDrive\デスクトップ\角度の指示\採用案")
ENV_FILE = Path("C:/Users/waras/hitonote-design-lp/.env.local")
LOG_DIR = ROOT / "_fill_pose_logs"

FALLBACKS = ["gpt-image-1.5", "gpt-image-1"]
BLOCKED_MODELS: set[str] = set()


def load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())


# 不足14日分の仕様
TARGETS = [
    # (旧暦日, 名称, 角度, 手のひら向き)
    (4,  "マユヅキ",         45,  "up"),
    (10, "トカンヤ",         125, "up"),
    (11, "ジュウイチヤ",     135, "up"),
    (12, "ジュウニヤ",       145, "up"),
    (13, "アタラヨ",         160, "up"),
    (14, "マチヨイ",         170, "up"),
    (16, "イザヨイ",         170, "down"),
    (17, "タチマチ",         155, "down"),
    (18, "イマチ",           145, "down"),
    (19, "ネマチ",           135, "down"),
    (20, "フケマチ",         125, "down"),
    (21, "ニジュウイチヤ",   110, "down"),
    (22, "ニジュウニヤ",     100, "down"),
    (24, "ニジュウヨヤ",     75,  "down"),
]


COMMON_STYLE = (
    "Photorealistic full-body portrait of a young Japanese woman in her late 20s, slim athletic yoga practitioner. "
    "Long dark brown hair in a loose low ponytail with soft front bangs (alternatively a high top knot). "
    "Calm gentle expression, slight serene smile. "
    "Wearing matching deep PURPLE yoga outfit: cropped purple racerback sports bra (V-neck, thin crossover straps) "
    "and high-waisted PURPLE yoga leggings (full length). Bare feet. "
    "A small reddish heart-shaped accent visible on her left chest. "
    "Background: SOLID GREEN CHROMA KEY (#00B140), completely flat, no walls, no floor texture, no shadows on background. "
    "Lighting: soft even studio light, natural feminine glow. "
    "Composition: full body visible from head to toe, vertical portrait, figure perfectly centered, standing on both feet. "
    "Style: clean lifestyle/fitness studio photography, gentle and serene. "
    "Same exact woman as the reference set (face, body, hair, outfit consistently)."
)


def pose_description(angle: int, palm: str) -> str:
    palm_text = ("PALMS FACING UP toward the sky (open and receiving)"
                 if palm == "up" else "PALMS FACING DOWN toward the ground (calm and grounding)")
    direction = "UPWARD" if palm == "up" else "DOWNWARD (the second half of the cycle, arms below shoulder line)"

    if angle == 0:
        if palm == "up":
            pose = ("Both arms raised STRAIGHT UP overhead, palms together in prayer (gassho), "
                    "hands meeting at the apex above the crown. Arms parallel, vertical line, no gap.")
        else:
            pose = ("Both arms straight DOWN at sides ('kiotsuke' attention posture), hands beside thighs, vertical.")
    elif angle == 180:
        pose = ("Both arms FULLY EXTENDED HORIZONTALLY to the sides at shoulder height, T-pose, "
                "180 degree gap between arms, palms forward.")
    else:
        half = angle / 2.0
        if palm == "up":
            pose = (f"Both arms raised symmetrically in a V-shape ABOVE her head, "
                    f"with a {angle} degree angular gap between the arms. "
                    f"Each arm tilted {half:.0f} degrees outward from the vertical-upward direction. "
                    f"Right arm points up-and-to-the-right, left arm up-and-to-the-left. "
                    f"Hands open, fingers extended.")
        else:
            pose = (f"Both arms in a symmetric DOWNWARD V-shape from the body sides, "
                    f"with a {angle} degree angular gap between the arms. "
                    f"Each arm tilted {half:.0f} degrees outward from the vertical-downward direction. "
                    f"Right arm points down-and-to-the-right, left arm down-and-to-the-left. "
                    f"Hands relaxed, fingers slightly extended.")
    return f"Pose: {pose} {palm_text}."


def build_prompt(angle: int, palm: str) -> str:
    return f"{COMMON_STYLE}\n\n{pose_description(angle, palm)}"


def generate_one(client, day: int, name: str, angle: int, palm: str, model_order: list[str]) -> dict:
    palm_jp = "上向き" if palm == "up" else "下向き"
    out_path = DST / f"{day:02d}日_{name}_{angle}度.png"
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  [SKIP] {out_path.name}", flush=True)
        return {"ok": True, "skipped": True}
    prompt = build_prompt(angle, palm)
    last_err = None
    for model in model_order:
        if model in BLOCKED_MODELS:
            continue
        try:
            print(f"  -> [{model}] day {day:02d} {name} angle={angle} palm={palm_jp}", flush=True)
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
            DST.mkdir(parents=True, exist_ok=True)
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

    DST.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Targets: {len(TARGETS)} days")
    t_start = time.time()
    results = []
    for i, (day, name, angle, palm) in enumerate(TARGETS, 1):
        print(f"[{i}/{len(TARGETS)}] day {day:02d} {name}")
        res = generate_one(client, day, name, angle, palm, list(FALLBACKS))
        results.append({"day": day, "name": name, "angle": angle, "palm": palm, **res})

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
