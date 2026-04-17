#!/usr/bin/env python3
"""
Schumann Resonance Fetcher v4 - Claude 4.7 Vision Edition
Tomskスペクトログラムを Claude Opus 4.7 で解析して F1〜F5 を抽出
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
TOMSK_URLS = [
    "https://sos70.ru/provider.php?file=shm.jpg",
    "https://sos70.ru/provider.php?file=srf.jpg",
    "https://sosrff.tsu.ru/new/shm.jpg",
]

OUTPUT_DATA = "schumann_data.json"
OUTPUT_HISTORY = "schumann_history.json"
IMAGE_CACHE = "latest_spectrogram.jpg"
MAX_HISTORY = 2880  # 15分×2880 = 30日分

MODEL = "claude-opus-4-7"


def fetch_tomsk_image() -> tuple[bytes | None, str | None]:
    """Tomskから最新のスペクトログラム画像を取得"""
    headers = {
        "User-Agent": "Mozilla/5.0 (schumann-monitor; research)",
        "Accept": "image/jpeg,image/*,*/*",
    }
    for url in TOMSK_URLS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
                if len(data) > 1000:  # 最低限の画像サイズチェック
                    print(f"✓ Fetched image from {url} ({len(data)} bytes)")
                    return data, url
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            print(f"✗ Failed {url}: {e}")
            continue
    return None, None


def analyze_with_claude(image_bytes: bytes) -> dict:
    """Claude 4.7 Visionでスペクトログラムを解析"""
    client = anthropic.Anthropic()  # API key from ANTHROPIC_API_KEY env var
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    prompt = """このTomsk大学のシューマン共振スペクトログラム画像を解析してください。

画像は時間×周波数の2次元プロットです。横軸が時刻、縦軸が周波数（Hz）、色の明るさがパワーを表します。

以下のタスクを実行してください：

1. 画像の**右端（最新時刻）**で、シューマン共振の各モード（F1〜F5）の中心周波数を読み取ってください
   - F1: 約7-8Hz付近の一番下の帯
   - F2: 約14Hz付近
   - F3: 約20Hz付近
   - F4: 約26Hz付近
   - F5: 約33Hz付近
2. 各モードの信頼度（0-100）も評価してください
   - 帯がはっきり見える → 高信頼度
   - 薄い、ノイズが多い、不鮮明 → 低信頼度
3. 全体的な活動度（amplitude_level）: low/medium/high
4. 振幅変動が見える場合、どのモードが最も強いか

**必ず以下のJSON形式のみで回答してください。他の説明文は一切不要です：**

{
  "F1": {"hz": 7.83, "confidence": 85},
  "F2": {"hz": 14.1, "confidence": 80},
  "F3": {"hz": 20.3, "confidence": 75},
  "F4": {"hz": 26.4, "confidence": 60},
  "F5": {"hz": 33.8, "confidence": 40},
  "amplitude_level": "medium",
  "strongest_mode": "F1",
  "notes": "画像の観察メモ（簡潔に）"
}"""

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    )

    response_text = message.content[0].text.strip()
    # ```json フェンスを除去
    if response_text.startswith("```"):
        response_text = response_text.split("```")[1]
        if response_text.startswith("json"):
            response_text = response_text[4:]
        response_text = response_text.strip()

    return json.loads(response_text)


def calculate_polarization(utc_now: datetime.datetime) -> dict:
    """
    偏光状態の判定（Sentman 1987ベース）
    - 昼側（太陽が照らしている側）: 右回転偏光優位
    - 夜側: 左回転偏光優位
    Tomskは東経84.9度にあるので、UTC+5.6時間が現地太陽時
    """
    tomsk_local_hour = (utc_now.hour + utc_now.minute / 60 + 5.6) % 24
    is_day_tomsk = 6 <= tomsk_local_hour <= 18

    # 日本（東経135度、UTC+9）での判定
    japan_hour = (utc_now.hour + utc_now.minute / 60 + 9) % 24
    is_day_japan = 6 <= japan_hour <= 18

    # グローバル電離層の平均的状態（昼側面積で判定）
    # UTC 0:00時点で地球の昼夜中心軸が経度180度にある
    # ここでは日本視点を基準にする
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

    print(f"=== Schumann Fetch v4 @ {timestamp} ===")

    # 1. Tomsk画像を取得
    image_bytes, source_url = fetch_tomsk_image()
    if image_bytes is None:
        print("✗ All Tomsk URLs failed. Aborting.")
        # エラー状態を記録
        error_data = {
            "timestamp": timestamp,
            "status": "error",
            "error": "All Tomsk URLs unreachable",
        }
        save_json(OUTPUT_DATA, error_data)
        return

    # 2. キャッシュ画像として保存（GitHub Pagesで表示用）
    with open(IMAGE_CACHE, "wb") as f:
        f.write(image_bytes)

    # 3. Claude 4.7で解析
    try:
        analysis = analyze_with_claude(image_bytes)
        print(f"✓ Claude analysis: {analysis}")
    except Exception as e:
        print(f"✗ Claude API error: {e}")
        error_data = {
            "timestamp": timestamp,
            "status": "error",
            "error": f"Claude API failed: {e}",
        }
        save_json(OUTPUT_DATA, error_data)
        return

    # 4. 偏光状態を計算
    polarization = calculate_polarization(utc_now)

    # 5. 統合データ作成
    data = {
        "timestamp": timestamp,
        "status": "ok",
        "source_url": source_url,
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

    # 6. 履歴に追加
    history = load_history()
    # 履歴用は軽量化
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
