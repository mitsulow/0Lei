# シューマン共振 公式API v1 仕様

Onesea / ツキヨガ / MMM アプリなどの外部アプリが `schumann_data.json` を
読むだけで共振値を表示できるようにするための、凍結済みスキーマ仕様。

- **取得URL**: `https://mitsulow.github.io/0Lei/schumann_data.json`
- **更新頻度**: 15分毎（外部トリガー。フェイルセーフの GitHub cron は1時間毎。
  トムスク観測所側が未更新の回は `timestamp` のみ進む）
- **キャッシュバスター推奨**: GitHub Pages の CDN キャッシュを避けるため
  `?t=` にミリ秒タイムスタンプを付与すること
  例: `fetch("https://mitsulow.github.io/0Lei/schumann_data.json?t=" + Date.now())`
- **CORS**: GitHub Pages は `Access-Control-Allow-Origin: *` を返すのでブラウザから直接 fetch 可

## スキーマ変更ルール（重要）

1. **フィールドの追加のみ可**。既存フィールドの型変更・意味変更・削除は不可
2. 変更・削除が必要になった場合は `schema_version` をメジャーアップ（`2.0`）し、
   旧スキーマのファイルを別名で並行提供する
3. 読む側は未知のフィールドを無視すること（追加に対して前方互換）

## フィールド一覧

### トップレベル

| フィールド | 型 | 意味 |
|---|---|---|
| `schema_version` | string | このスキーマの版。現在 `"1.0"` |
| `timestamp` | string | 読み取り実行時刻。**UTC** ISO 8601（内部保存はすべてUTC） |
| `updated_jst` | string | 同時刻の人間可読 JST 文字列。例 `"2026-07-30 21:03 JST"`。アプリ側の変換不要 |
| `status` | string | `"ok"` 固定（エラー時はファイル自体が更新されない） |
| `source_line` / `source_spectro` | string | 読み取り元画像URL（sos70.ru） |
| `model` | string | 読み取り方式。現在 `"pixel-extraction-v6.1-ocr"`（ローカル処理・API不使用） |
| `modes` | object | F1〜F5 の観測値。下記参照 |
| `target_hz` | number | MMM 目標周波数 `8.0219032748`（恒星日 86,164 秒 ÷ (8回転 × 86,400 秒) 由来） |
| `distance_to_target_hz` | number \| null | `F1現在値 − target_hz`。**負値 = 未達**。F1 欠損時は null |
| `condition` | string | 今日の共振の荒れ具合: `"calm"` \| `"active"` \| `"storm"` \| `"unknown"`（スペクトログラム解析。取得失敗時 unknown） |
| `strongest_mode` | string | 理論値に最も近いモード名。例 `"F1"` |
| `notes` | string | 日本語の自動観察メモ |
| `polarization` | object | 磁場偏光（昼=右回転/夜=左回転）。`state`, `state_jp`, `japan_hour`, `tomsk_hour` 等 |
| `data_age_min` | object | モード毎の観測データ鮮度（分）。トムスク側の遅延を含む |
| `source_unchanged` | boolean | `true` = 前回と同一画像だったため timestamp のみ更新した回 |
| `events` | array | プッシュ通知用イベント（下記）。新しいものが末尾。最大100件保持 |

### `modes.F1` 〜 `modes.F4`（`F5` は常に `hz: null`）

| フィールド | 型 | 意味 |
|---|---|---|
| `hz` | number \| null | 周波数（Hz）。読み取り不能時 null |
| `confidence` | number | 信頼度 0〜100。軸OCR検証成功時 95、静的フォールバック時 60 以下 |
| `calibration` | string | `"ocr"`（軸目盛りOCR検証済）\| `"static-fallback"` |
| `amp` | number \| null | 振幅（pT） |
| `q` | number \| null | Q値（共振の鋭さ） |

### `events[]` の要素

| フィールド | 型 | 意味 |
|---|---|---|
| `type` | string | イベント種別。現在は `"f1_above_8.0"`（F1 が 8.0Hz を下から上抜けした回）のみ |
| `at` | string | 発生時刻（UTC ISO 8601） |

## 関連ファイル（参考・スキーマ凍結対象外）

| URL | 内容 |
|---|---|
| `.../0Lei/schumann_history.json` | 直近30日のローリング履歴（15分刻み配列） |
| `.../0Lei/history/YYYY-MM.json` | 月別の永久履歴（生データ） |
| `.../0Lei/history/YYYY-MM.daily.json` | 前月確定後の日次集計（min/max/mean/count） |
| `.../0Lei/history/monthly_summary.json` | 月平均サマリー（ダッシュボードの月平均トレンド用） |
| `.../0Lei/graph_stats.json` | 直近3日間の統計（3日平均など） |

## 表示実装の最小例

```js
const r = await fetch("https://mitsulow.github.io/0Lei/schumann_data.json?t=" + Date.now());
const d = await r.json();
const f1 = d.modes?.F1?.hz;                      // 例 7.93
const dist = d.distance_to_target_hz;            // 例 -0.0919 (未達)
console.log(`F1 ${f1} Hz / 目標まで ${dist} Hz / ${d.updated_jst} / ${d.condition}`);
```
