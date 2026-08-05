# シューマン共振「宝の山」データの出典

地球のシューマン共振（第1〜第4モード F1-F4）を、トムスク国立大学の折れ線グラフ
（srf.jpg）から5分刻みで読み取った生データ集。2011年10月〜現在。

## 5分生値データ（history/{YYYY-MM}.json）— 宝の山の本体

すべて**トムスク国立大学 sosrff.tsu.ru の周波数線グラフ srf.jpg**が原典。
同じ観測所・同じ読み取りエンジン（fetch_schumann_v6 のピクセル抽出）で統一。

| 期間 | 入手経路 | src |
|---|---|---|
| 2023-08 〜 現在（密・毎日） | schumann-frequency.com の線グラフアーカイブ（トムスク再配信）を毎日取得し三重クロスチェック | `cross` |
| 2011-10 〜 2023-07（飛び石） | Internet Archive (Wayback Machine) の sosrff.tsu.ru / www.sosrff.tsu.ru srf.jpg キャプチャ | `line` |
| 現在（ライブ・15分毎） | sos70.ru（トムスク公式ミラー）の srf.jpg を GitHub Actions で15分毎に読み取り | `line` |

- `cross` = 1枚に3日分写る性質を使い、同じ5分スロットを最大3枚から読んで合議（中央値±0.12Hz外を棄却）した検証済み値。`agree` に合議枚数を記録。
- `line` = 単一画像からの読み取り。
- 保険: 毎回の観測で schumann-frequency.com から直近数日を回収し、ライブが落ちた穴を自動で埋める（recover_from_archive）。

## 日別サマリー（history/daily_summary.json）

上記5分生値の**日別平均（JST区切り）だけ**で構成。レガシー日平均は使わない（真A案・2026-08-06）。

## 参考・別系統データ（宝の山には混ぜない）

| ファイル | 出典 | 備考 |
|---|---|---|
| history/legacy_daily.json | schumann-resonance.earth アーカイブから2023年に抽出した日平均（トムスク由来） | 1日1点の平均値で日々変動が潰れるため、宝の山・グラフには不使用。参照用に温存 |
| history/solar_daily.json | GFZ Potsdam Kp/Ap 地磁気指数（CC BY 4.0） | 太陽活動との相関表示用 |

## 読み取り精度について

- 白い透かし "Copyright@ http://sosrff.tsu.ru" が F1(白線)に混入し中日の値を約0.16Hz
  低く歪めるバグを2026-08-06に根治（F1マスクから透かしボックス除外）。
- 軸目盛りは画像ごとにOCR校正。前後5点の中央値から逸脱した読みは誤読として除外。
- 検証: schumann-frequency.com の値と本家ライブ値の差は0.002〜0.03Hz（校正不要レベル）。

## 取り尽くしの記録

トムスク源で入手可能なデータは Wayback を www 系統まで含めて完全網羅済み（srf.jpg 全キャプチャ）。
X の @schumannbot も同じトムスク画像の再投稿だが、古い投稿は運営が削除しており
（2020年は消滅・保持は直近約2年のみ）、飛び地期間は復元不可能と確認済み（2026-08-06）。
他観測所（Sierra Nevada / Cumiana / HeartMath）は別機器・別基準のため一貫性維持のため不採用。
