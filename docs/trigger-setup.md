# 15分きっかり更新の外部トリガー設定手順

GitHub Actions の cron は混雑時に30〜60分遅延するため、外部サービス
(cron-job.org / 無料) から `repository_dispatch` を15分毎に叩いて
きっかり更新させる。GitHub 側の cron は1時間毎のフェイルセーフとして残してある。

**ランニングコスト: ゼロ**（cron-job.org 無料プラン + GitHub 無料枠）

---

## 1. GitHub Fine-grained PAT の発行

1. GitHub にログイン → 右上アイコン → **Settings**
2. 左メニュー最下部 **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
3. 設定内容:
   - **Token name**: `schumann-trigger`（任意）
   - **Expiration**: 1 year（最長を推奨。期限切れ前にメール通知が来る）
   - **Repository access**: **Only select repositories** → `mitsulow/0Lei` のみ選択
   - **Permissions** → **Repository permissions** → **Contents**: **Read and write**
     （repository_dispatch を叩くのに必要なのはこれだけ。他は No access のまま）
4. **Generate token** を押し、表示されたトークン（`github_pat_...`）をコピー。
   **この画面を閉じると二度と表示されない**ので必ず控えること。

> ⚠️ トークンは秘密情報。ブログ・リポジトリ・スクショに絶対に載せない。

## 2. cron-job.org にジョブ登録

1. <https://cron-job.org> で無料アカウント作成 → ログイン
2. **CREATE CRONJOB** をクリック
3. **Common** タブ:
   - **Title**: `schumann-update`
   - **URL**: `https://api.github.com/repos/mitsulow/0Lei/dispatches`
   - **Execution schedule**: **Every 15 minutes**
     （きっかり 0/15/30/45 分にしたい場合は Custom → Minutes で `0,15,30,45` を選択）
4. **Advanced** タブ:
   - **Request method**: `POST`
   - **Headers** に以下の3行を追加:

     | Key | Value |
     |---|---|
     | `Authorization` | `Bearer github_pat_XXXX`（手順1のトークン） |
     | `Accept` | `application/vnd.github+json` |
     | `User-Agent` | `schumann-cron` |

   - **Request body**:

     ```json
     {"event_type":"schumann-update"}
     ```

5. **CREATE** で保存。

## 3. 動作確認

- cron-job.org のジョブ詳細 → **TEST RUN** を実行 → ステータス **204 No Content** なら成功
  （401 は Authorization ヘッダの誤り、404 はトークンの Repository access / URL の誤り）
- GitHub の `0Lei` → **Actions** タブに `Schumann Resonance v6` の実行が
  即時に現れる（イベント名 `repository_dispatch`）
- 手動テストは `Actions → Schumann Resonance v6 → Run workflow`（workflow_dispatch）でも可

curl での確認例（PC から）:

```bash
curl -X POST \
  -H "Authorization: Bearer github_pat_XXXX" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/mitsulow/0Lei/dispatches \
  -d '{"event_type":"schumann-update"}'
```

## 4. 仕組みメモ

- workflow には `concurrency` を設定済み。実行中に次のトリガーが来ても多重起動しない
  （待機は1件だけ、それ以上は自動破棄）
- 取得した srf.jpg の SHA-256 が前回と同一（トムスク側未更新）の場合、
  読み取り・グラフ生成をスキップして timestamp だけ更新する（`source_unchanged: true`）
- PAT の期限が切れると cron-job.org が 401 を返し続ける。GitHub cron（1時間毎）は
  生き続けるので更新は止まらないが、15分更新に戻すにはトークン再発行 → ヘッダ差し替え
