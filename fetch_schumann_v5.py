#!/usr/bin/env python3
"""
Schumann Resonance Fetcher v5 - Line Graph Primary
srf.jpg（折れ線グラフ）をメインで読み、shm.jpg（スペクトログラム）で補強
Claude Opus 4.7 Vision
"""
import os
import json
import base64
import datetime
import urllib.request
import urllib.error
from pathlib import Path

import anthropic

# --- 設定 ---
# メイン: srf.jpg = 折れ線グラフ（各モード中心周波数の時系列）
# 補助: shm.jpg = スペクトログラム（帯の確認用）
URLS_LINE = [
    "https://sos70.ru/provider.php?file=srf.jpg",
    "https://sosrff.tsu.ru/new/srf.jpg",
]
URLS_SPECTRO = [
    "https://sos70.ru/provider.php?file=shm.jpg",
    "https://sosrff.tsu.ru/new/shm.jpg",
]

OUTPUT_DATA = "schumann_data.json"
OUTPUT_HISTORY = "schumann_history.json"
IMAGE_LINE = "latest_linegraph.jpg"
IMAGE_SPECTRO = "latest_spectrogram.jpg"
MAX_HISTORY = 2880  # 15分×2880 = 30日分

MODEL = "claude-opus-4-7"


def fetch_image(urls: list[str]) -> tuple[bytes | None, str | None]:
    headers = {
        "User-Agent": "Mozilla/5.0 (schumann-monitor; research)",
        "Accept": "image/jpeg,image/*,*/*",
    }
    for url in urls:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                if len(data) > 1000:
                    print(f"✓ Fetched {url} ({len(data)} bytes)")
                    return data, url
        except Exception as e:
            print(f"✗ Failed {url}: {e}")
            continue
    return None, None


def analyze_with_claude(line_bytes: bytes, spectro_bytes: bytes | None) -> dict:
    """
    折れ線グラフをメインに、スペクトログラムを補助として周波数を読み取る
    """
    client = anthropic.Anthropic()
    line_b64 = base64.standard_b64encode(line_bytes).decode("utf-8")

    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": line_b64,
            },
        }
    ]

    if spectro_bytes:
        spectro_b64 = base64.standard_b64encode(spectro_bytes).decode("utf-8")
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": spectro_b64,
                },
            }
        )

    prompt = """2枚の画像はTomsk大学のシューマン共振データです。

**画像1（メイン）: 折れ線グラフ（srf.jpg）**
- 横軸：時刻（UTC）、縦軸：各モードの中心周波数（Hz）
- 複数の色の線が各モード（F1〜F5）の周波数時系列を表す
- **この画像から右端（最新時刻）の各モードの数値を正確に読み取ってください**
- 縦軸の目盛りを正確に見ること。データ欠損領域（線が途切れている部分）は無視して、その直前の有効な値を読むこと

**画像2（補助）: スペクトログラム（shm.jpg）**
- 折れ線グラフで読み取れない場合の補助として参照

**凡例（典型的な線の色分け、要確認）**
- F1 (約7.83Hz付近): 白または黄色の線（最も下）
- F2 (約14Hz付近): 2番目の線
- F3 (約20Hz付近): 赤系の線
- F4 (約26Hz付近): その上の線
- F5 (約33Hz付近): 最上部の線

**タスク**
1. 折れ線グラフの右端（最新時刻の確実な値）から F1〜F5 を小数第2位まで読み取る
2. 各モードの信頼度（0-100）を評価
   - 線がはっきり見えて目盛りが読める → 高信頼度（80-95）
   - 線が薄い、目盛りが読みにくい、線が途切れている → 低信頼度
3. 全体的な活動度 amplitude_level: low/medium/high
4. 注目すべき点（notes）を簡潔に日本語で

**必ず以下のJSON形式のみで回答。他の文章は一切書かないこと：**

{
  "F1": {"hz": 7.88, "confidence": 90},
  "F2": {"hz": 14.12, "confidence": 85},
  "F3": {"hz": 20.30, "confidence": 85},
  "F4": {"hz": 26.40, "confidence": 70},
  "F5": {"hz": 33.80, "confidence": 50},
  "amplitude_level": "medium",
  "strongest_mode": "F1",
  "notes": "観察メモ"
}"""

    content.append({"type": "text", "text": prompt})

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": content}],
    )

    response_text = message.content[0].text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("```")[1]
        if response_text.startswith("json"):
            response_text = response_text[4:]
        response_text = response_text.strip()

    return json.loads(response_text)


def calculate_polarization(utc_now: datetime.datetime) -> dict:
    tomsk_local_hour = (utc_now.hour + utc_now.minute / 60 + 5.6) % 24
    is_day_tomsk = 6 <= tomsk_local_hour <= 18

    japan_hour = (utc_now.hour + utc_now.minute / 60 + 9) % 24
    is_day_japan = 6 <= japan_hour <= 18

    polarization = "right" if is_day_japan else "left"
    polarization_jp = "右回転（昼）" if is_day_japan else "左回転（夜）"

    return {
        "state": polarization,
        "state_jp": polarization_jp,
        "japan_hour": round(japan_hour, 2),
        "tomsk_hour": round(tomsk_local_hour, 2),
        "is_day_japan": is_day_japan,
        "is_day_tomsk": is_day_tomsk,
    }


def load_history() -> list:
    if Path(OUTPUT_HISTORY).exists():
        try:
            with open(OUTPUT_HISTORY, "r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return []
    return []


def save_json(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def main():
    utc_now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = utc_now.isoformat()

    print(f"=== Schumann Fetch v5 @ {timestamp} ===")

    # 1. 折れ線グラフ（メイン）を取得
    line_bytes, line_url = fetch_image(URLS_LINE)
    if line_bytes is None:
        print("✗ Line graph fetch failed")
        save_json(OUTPUT_DATA, {
            "timestamp": timestamp,
            "status": "error",
            "error": "Line graph unreachable",
        })
        return

    with open(IMAGE_LINE, "wb") as f:
        f.write(line_bytes)

    # 2. スペクトログラム（補助）も取得（失敗しても続行）
    spectro_bytes, spectro_url = fetch_image(URLS_SPECTRO)
    if spectro_bytes:
        with open(IMAGE_SPECTRO, "wb") as f:
            f.write(spectro_bytes)

    # 3. Claude 4.7で解析（折れ線メイン、スペクトログラム補助）
    try:
        analysis = analyze_with_claude(line_bytes, spectro_bytes)
        print(f"✓ Claude analysis: {analysis}")
    except Exception as e:
        print(f"✗ Claude API error: {e}")
        save_json(OUTPUT_DATA, {
            "timestamp": timestamp,
            "status": "error",
            "error": f"Claude API failed: {e}",
        })
        return

    # 4. 偏光状態
    polarization = calculate_polarization(utc_now)

    # 5. 統合データ
    data = {
        "timestamp": timestamp,
        "status": "ok",
        "source_line": line_url,
        "source_spectro": spectro_url,
        "model": MODEL,
        "modes": {
            "F1": analysis.get("F1", {}),
            "F2": analysis.get("F2", {}),
            "F3": analysis.get("F3", {}),
            "F4": analysis.get("F4", {}),
            "F5": analysis.get("F5", {}),
        },
        "amplitude_level": analysis.get("amplitude_level", "unknown"),
        "strongest_mode": analysis.get("strongest_mode", ""),
        "notes": analysis.get("notes", ""),
        "polarization": polarization,
    }

    save_json(OUTPUT_DATA, data)
    print(f"✓ Saved {OUTPUT_DATA}")

    # 6. 履歴
    history = load_history()
    history_entry = {
        "t": timestamp,
        "F1": analysis.get("F1", {}).get("hz"),
        "F2": analysis.get("F2", {}).get("hz"),
        "F3": analysis.get("F3", {}).get("hz"),
        "F4": analysis.get("F4", {}).get("hz"),
        "F5": analysis.get("F5", {}).get("hz"),
        "c1": analysis.get("F1", {}).get("confidence"),
    }
    history.append(history_entry)
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]
    save_json(OUTPUT_HISTORY, history)
    print(f"✓ History updated ({len(history)} entries)")


if __name__ == "__main__":
    main()
