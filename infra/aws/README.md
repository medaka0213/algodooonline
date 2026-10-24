# infra/aws — 本番 AWS サーバーレス構成

アカウント `803488550383` / `ap-northeast-1`。アクセスが無いときに課金されるのはストレージ（DynamoDB・S3・CloudWatch Logs）だけになる構成です。

| 役割 | リソース | 待機コスト |
|---|---|---|
| アプリ | Lambda `algodooonline-web`（python3.12、Mangum、1024MB） | 0（実行時間課金） |
| 入口 | API Gateway HTTP API + regional カスタムドメイン `algodooonline.net` / `www.algodooonline.net` | 0（リクエスト課金） |
| 証明書 | ACM（regional、DNS 検証） | 0 |
| DB | DynamoDB `algodoo-main`（on-demand、PITR、削除保護） | ストレージのみ |
| 添付 | 既存 S3 `img.algodooonline.net`（Terraform 管理外。IAM で `IMAGE/*`・`DATA/*` への Put のみ許可） | ストレージのみ（既存） |
| 認証 | 既存 Cognito `AlgonTest` に App Client `algodooonline-web` を追加（プールは管理外） | 0 |
| ログ | CloudWatch Logs（Lambda・アクセスログ、保持 14 日） | ストレージのみ |

使わないもの: ALB、NAT Gateway、VPC、プロビジョンドキャパシティ、Secrets Manager、KMS CMK、ECR。`LEGACY_X_API_KEY` は `random_password` で生成し Lambda 環境変数（AWS 管理キーで暗号化）に入れます。最悪時の課金は HTTP API のスロットリング（既定 20 req/s・burst 50）で頭打ちにします。

state は `guppy-terraform-state` の `algodooonline/terraform.tfstate`（`guppy-monorepo/deploy/terraform/cognito` と同じバケット・別キー）。

## デプロイ

```bash
sh scripts/build_lambda.sh                 # dist/lambda.zip
terraform -chdir=infra/aws init
terraform -chdir=infra/aws plan
terraform -chdir=infra/aws apply
```

この時点では DNS は旧 CloudFront のままです。`terraform output invoke_url` の execute-api URL で動作確認できます（Cookie は `Secure`、ログインは実 Cognito）。

## 切替手順（本番）

1. **新テーブルへ試し移行**: `DDB_TABLE_NAME=algodoo-main uv run python scripts/migrate_v2_import.py --recompute-counts`（dry-run）で件数を確認し、`--apply` で投入して execute-api URL で表示を確認する。
2. **旧 API の書き込み停止**: 旧 API Gateway `helloworld`（`ie5vrztqa7`）のステージのスロットリングを 0 にする。旧 SPA は閲覧不可になるため、ここから手順 4 までを短時間で行う。
3. **本移行**: `migrate_v2_import.py --apply --recompute-counts` をもう一度実行する（upsert なので冪等）。差分レポートを確認する。
4. **DNS 切替**: `sh scripts/cutover_dns.sh lambda`（apex の A alias を UPSERT。`www` は apex への CNAME なので追従する）。
5. **確認**: `/`、`/i/BBS` 等の一覧・詳細、既存ユーザーでのログイン、投稿・返信・Like、IMAGE/DATA 添付、`/BBS` → `/i/BBS` リダイレクト。

## 切り戻し

`sh scripts/cutover_dns.sh legacy` で apex を旧 CloudFront（`E7E2GUMAI90BB`）に戻し、旧 API のスロットリングを元に戻す。切替後に新側で書かれたデータは旧テーブルには戻らない。

## 後片付け（安定稼働を確認してから）

旧 Lambda `chalice-test-prod`、API Gateway `helloworld`（usage plan / API key 含む）、旧 4 テーブル `thread` / `log` / `like` / `user`、旧フロント S3 `algodooonline.net` と CloudFront `E7E2GUMAI90BB`。`img.algodooonline.net`（bucket と CloudFront）は引き続き使用する。
