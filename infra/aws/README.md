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
| 自動デプロイ | GitHub OIDC プロバイダ + IAM ロール `algodooonline-github-deploy`（Lambda のコード更新だけ許可） | 0 |

使わないもの: ALB、NAT Gateway、VPC、プロビジョンドキャパシティ、Secrets Manager、KMS CMK、ECR。`LEGACY_X_API_KEY` は `random_password` で生成し Lambda 環境変数（AWS 管理キーで暗号化）に入れます。最悪時の課金は HTTP API のスロットリング（既定 20 req/s・burst 50）で頭打ちにします。

state は `guppy-terraform-state` の `algodooonline/terraform.tfstate`（`guppy-monorepo/deploy/terraform/cognito` と同じバケット・別キー）。

## 制約

- **1 回の送信は約 4.7MB まで**：Lambda の呼び出しペイロード上限（6MB）を、API Gateway が本文を base64 化した後に超えると、アプリに届く前に API Gateway が素の 413 を返します。本番で実測した境界は 4,718,592 バイト（4.5 MiB）です。画面のフォームは、これに余裕を持たせた 4,500,000 バイト（`MAX_FORM_BODY_BYTES`）を送信前に確認し、超えるときはメッセージを出して止めます。base64 と URL エンコードで本文はファイルの約 1.4 倍になるので、ファイルの合計では約 3MB が目安です。
- それより大きなファイルを扱うには、ブラウザから S3 へ署名付き URL で直接アップロードする方式が必要です（現在は未対応）。

## デプロイ

```bash
sh scripts/build_lambda.sh                 # dist/lambda.zip
terraform -chdir=infra/aws init
terraform -chdir=infra/aws plan
terraform -chdir=infra/aws apply
```

この時点では DNS は旧 CloudFront のままです。`terraform output invoke_url` の execute-api URL で動作確認できます（Cookie は `Secure`、ログインは実 Cognito）。

## 自動デプロイ（main へのマージ）

`main` への push で、`.github/workflows/ci.yml` の `deploy` ジョブが Lambda のコードだけを差し替えます。インフラ（IAM・API Gateway・DynamoDB など）は自動では変わらず、これまでどおり手元で `terraform plan` を見てから `apply` します。

流れ: 全テスト通過 → `lambda` ジョブでテスト済みの zip を artifact に保存 → `deploy` ジョブが OIDC でロール `algodooonline-github-deploy` を引き受け → `update-function-code` → ハッシュ照合 → 本番ドメインのスモークテスト（`/healthz`、`/i/BBS`、ホーム）。

- 認証は GitHub OIDC で、アクセスキーは GitHub に置きません。ロールを引き受けられるのは `medaka0213/algodooonline` の `main` ブランチ上の実行だけで、権限は `algodooonline-web` への `lambda:UpdateFunctionCode` と `lambda:GetFunction` に限っています。
- zip は再現できません（同じコミットを 2 回ビルドしても、`.pyc` とパッケージの `RECORD`・`uv_cache.json` が違うためハッシュが変わります。ソースコードは同一です）。そのため、`main` への push は、ドキュメントだけの変更でも毎回 Lambda を差し替えます。差し替えは一瞬で切り替わり、直後にスモークテストが走ります。
- ハッシュ照合は 2 か所です。更新前の照合は、同じ実行をそのまま再実行したとき（同じ artifact を使うので、ハッシュが本番と同じになる）だけ「何もしない」で終わらせます。更新後の照合は、テストした zip がそのまま AWS に入ったことを確かめます。
- Lambda は `ignore_changes = [filename, source_code_hash]` にしてあり、CI がコードを更新しても `terraform plan` に差分は出ません。plan 時に zip ファイルは必要です（どのビルドでも構いません）。
- 同時に走るデプロイは 1 つだけです。後のマージは先のデプロイが終わるまで待ちます。

### 有効化（初回のみ）

`deploy` ジョブはリポジトリ変数 `AWS_DEPLOY_ROLE_ARN` が空のあいだ実行されません（スキップ）。ロールを作ってから変数を設定すると有効になります。

```bash
terraform -chdir=infra/aws apply        # OIDC プロバイダ・ロール・ポリシーを作成
gh variable set AWS_DEPLOY_ROLE_ARN --repo medaka0213/algodooonline \
  --body "$(terraform -chdir=infra/aws output -raw github_deploy_role_arn)"
```

OIDC プロバイダはアカウントに 1 つしか作れません。別のスタックが先に作った場合は、`terraform import` で取り込んでください。

### 止めたいとき・戻したいとき

- 自動デプロイを止める：リポジトリ変数 `AWS_DEPLOY_ROLE_ARN` を削除する（`gh variable delete AWS_DEPLOY_ROLE_ARN`）。
- 問題のあるデプロイを戻す：問題のコミットを revert してマージする（数分で前のコードに戻る）。急ぐときは、以前に成功した Actions の `main` の実行を再実行する。
- `main` に直接 push できると、PR の CI を通さずにデプロイされます。「PR 必須 + CI の通過必須」のブランチ保護を GitHub で設定してください。

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
