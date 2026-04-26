"""
ツキヨガ v6: 62枚画像生成（昼30 + 夜30 + 特別2）

- プロンプト元: C:\\Users\\waras\\Downloads\\tsukiyoga_v6_62prompts.md
- 出力: ./pose_icons/{hiru|yoru}_{NN}_{name}.png + special_*.png
- API: OpenAI DALL-E 3、1024x1792、HD
- フォールバック: dall-e-3 → gpt-image-1.5 → gpt-image-1
"""
from __future__ import annotations
import base64
import io
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
ICONS_DIR = ROOT / "pose_icons"
LOG_DIR = ROOT / "_pose62_logs"
ENV_FILE = Path("C:/Users/waras/hitonote-design-lp/.env.local")
PROMPT_MD = Path(r"C:\Users\waras\Downloads\tsukiyoga_v6_62prompts.md")

FALLBACKS = ["gpt-image-1.5", "gpt-image-1"]
BLOCKED_MODELS: set[str] = set()

# ローマ字名（ファイル命名規則どおり）
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


def load_env() -> None:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())


def parse_prompts(md_text: str) -> dict:
    """MDファイルから (mode, day) -> 完成版プロンプト の辞書を作る。"""
    # 共通仕様（最初の```ブロック）
    common = re.search(r"## 共通仕様[^`]*```([\s\S]*?)```", md_text)
    if not common:
        raise RuntimeError("共通仕様セクションが見つからない")
    common_text = common.group(1).strip()

    # 共通追加プロンプト（昼）
    hiru_extra = re.search(r"### 共通追加プロンプト（昼）[^`]*```([\s\S]*?)```", md_text)
    yoru_extra = re.search(r"### 共通追加プロンプト（夜）[^`]*```([\s\S]*?)```", md_text)
    if not hiru_extra or not yoru_extra:
        raise RuntimeError("共通追加プロンプトが見つからない")
    hiru_extra_text = hiru_extra.group(1).strip()
    yoru_extra_text = yoru_extra.group(1).strip()

    out = {}
    # 昼N or 夜N
    pattern = r"###\s+(昼|夜)(\d+)：[^\n]*?\n[\s\S]*?```([\s\S]*?)```"
    for m in re.finditer(pattern, md_text):
        mode_jp = m.group(1)
        day = int(m.group(2))
        body = m.group(3).strip()
        mode = "hiru" if mode_jp == "昼" else "yoru"
        extra = hiru_extra_text if mode == "hiru" else yoru_extra_text
        full = (
            body
            .replace("[共通仕様]", common_text)
            .replace(f"[共通追加プロンプト（{mode_jp}）]", extra)
        ).strip()
        out[(mode, day)] = full

    # 特別1, 特別2
    sp_pattern = r"### 特別(\d+)：[^\n]*?\n[\s\S]*?```([\s\S]*?)```"
    for m in re.finditer(sp_pattern, md_text):
        n = int(m.group(1))
        body = m.group(2).strip()
        full = body.replace("[共通仕様]", common_text).strip()
        out[("special", n)] = full

    return out


def build_filename(mode: str, day: int) -> str:
    if mode == "special":
        if day == 1:
            return "special_01_noon_transition.png"
        return "special_02_midnight_transition.png"
    name = NAMES.get(day, f"day{day:02d}")
    return f"{mode}_{day:02d}_{name}.png"


def generate_one(client, mode: str, day: int, prompt: str, model_order: list[str]) -> dict:
    out_path = ICONS_DIR / build_filename(mode, day)
    if out_path.exists() and out_path.stat().st_size > 0:
        print(f"  [SKIP] (exists) {out_path.name}", flush=True)
        return {"ok": True, "skipped": True}
    last_err = None
    for model in model_order:
        if model in BLOCKED_MODELS:
            continue
        try:
            print(f"  -> [{model}] {mode} {day:02d} ...", flush=True)
            t0 = time.time()
            kwargs = dict(model=model, prompt=prompt, n=1)
            if model == "dall-e-3":
                kwargs["size"] = "1024x1792"
                kwargs["quality"] = "hd"
                kwargs["response_format"] = "b64_json"
            else:
                # gpt-image系は1024x1536が縦長
                kwargs["size"] = "1024x1536"
                kwargs["quality"] = "high"
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
                # このプロンプトはこのモデルでは不可。次モデルへフォールバック（永続ブロックはしない）
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

    md_text = PROMPT_MD.read_text(encoding="utf-8")
    prompts = parse_prompts(md_text)
    print(f"parsed prompts: {len(prompts)}", flush=True)

    arg = sys.argv[1] if len(sys.argv) > 1 else "priority"

    if arg == "priority":
        # 4聖点 × hiru/yoru = 8枚
        targets = []
        for d in [1, 7, 15, 23]:
            targets.append(("hiru", d))
            targets.append(("yoru", d))
    elif arg == "rest":
        priority_set = {("hiru", d) for d in [1, 7, 15, 23]} | {("yoru", d) for d in [1, 7, 15, 23]}
        targets = [k for k in prompts.keys() if k not in priority_set]
        # special も含める
    elif arg == "all":
        targets = list(prompts.keys())
    elif arg.startswith("hiru:") or arg.startswith("yoru:") or arg.startswith("special:"):
        mode, days = arg.split(":")
        targets = [(mode, int(d)) for d in days.split(",")]
    else:
        print(f"unknown arg: {arg}", flush=True)
        sys.exit(2)

    model_order = list(FALLBACKS)
    print(f"Model order: {model_order}", flush=True)
    print(f"Targets: {len(targets)}", flush=True)

    t_start = time.time()
    results = []
    for i, key in enumerate(targets, 1):
        mode, day = key
        prompt = prompts.get(key)
        if not prompt:
            print(f"[{i}/{len(targets)}] {mode} {day} : prompt not found", flush=True)
            results.append({"mode": mode, "day": day, "ok": False, "error": "no_prompt"})
            continue
        print(f"[{i}/{len(targets)}] {mode} {day:02d}", flush=True)
        res = generate_one(client, mode, day, prompt, model_order)
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
