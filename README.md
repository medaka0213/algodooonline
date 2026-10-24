# algodooonline

2019 年の `../Algon2-APP` と `../Algon2-API` を、Python + `uv` 前提で統合した Algodoo Online のモノレポです。

旧仕様の受け入れ条件は [`SPEC.md`](SPEC.md) に固定しています。画面・認証・API・データ移行はこの仕様との差分がなくなるまで完了扱いにしません。

## 方針

- UI と API は `FastAPI + Jinja2` で統合し、1 アプリとして動かす
- 本番は AWS サーバーレス構成（Lambda + API Gateway HTTP API、`infra/aws`）。代替として Docker Compose セルフホスト構成（`docker-compose.prod.yml`）も残す
- 認証は Amazon Cognito（`AUTH_BACKEND=cognito`）。ローカル・CI は擬似セッション（`AUTH_BACKEND=local`）
- DynamoDB（本番: on-demand テーブル、ローカル: moto）を `ddb_single` の single-table 設計で使う
- 添付ファイルは S3（本番: 既存 bucket `img.algodooonline.net`、ローカル: moto）

## 構成

- `apps/web`: 画面と API をまとめた Python アプリ
- `packages/domain`: ドメインモデル
- `packages/data`: DynamoDB single-table モデルとデータ層
- `scripts`: ローカル起動・結合テスト・移行スクリプト
- `infra/aws`: 本番 AWS 構成（Terraform）
- `Dockerfile` / `docker-compose.prod.yml` / `deploy/`: 代替のセルフホスト実行基盤

## 開始コマンド

```bash
uv sync --all-packages
uv run --package algodoo-web uvicorn algodoo_web.main:app --reload
```

## Docker Compose（ローカル開発）

```bash
docker compose up
```

- アプリ: `http://localhost:8080`
- DynamoDB API mock: `http://localhost:8001`
- S3 API mock: `http://localhost:8002`

初回起動時にアプリが DynamoDB single-table を自動作成し、デモ用の thread/log/like を投入します。
ローカル compose では DynamoDB と S3 の API 互換 `moto_server` を別コンテナとして立ち上げます。アプリ側のデータアクセスは `boto3 + ddb_single`、添付保存は `boto3` S3 client のままです。

## 本番デプロイ（AWS サーバーレス）

Lambda + API Gateway HTTP API + DynamoDB on-demand + 既存 S3 / Cognito。アクセスが無ければ課金はストレージだけです。IaC は [`infra/aws`](infra/aws/README.md)（Terraform）にあり、切替・切り戻し手順もそこにまとめています。

```bash
sh scripts/build_lambda.sh          # dist/lambda.zip
terraform -chdir=infra/aws init
terraform -chdir=infra/aws apply
```

Lambda パッケージの結合テスト（Lambda 公式ランタイム + HTTP API 相当アダプタ越しに `integration_local.py`）:

```bash
docker compose --profile test-lambda up --abort-on-container-exit --exit-code-from integration-lambda
```

### 代替: Linux ホスト + Docker Compose

```bash
cp .env.production.example .env.production   # プレースホルダを実値に置換
docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
```

- `app`: マルチステージ `Dockerfile` でビルドした non-root イメージ（uvicorn workers）
- `dynamodb`: `amazon/dynamodb-local`（`-sharedDb` + 永続ボリューム）
- `s3` + `s3-init`: S3 互換の添付ストア（SeaweedFS。MinIO はイメージ配布終了のため置換）。管理キー・アプリ用キー・`IMAGE/`・`DATA/` だけの匿名 read は `s3` が起動時に設定し、バケットは `s3-init` が作成
- TLS はホスト側のリバースプロキシに委譲（`deploy/Caddyfile.example`）。アプリは `127.0.0.1:8080`、S3 ゲートウェイは `127.0.0.1:9000` にのみバインド
- 認証は実 Cognito。User Pool / App Client（client secret なし、`ALLOW_USER_PASSWORD_AUTH` + `ALLOW_REFRESH_TOKEN_AUTH`）を用意して `.env.production` に設定
- `AUTH_BACKEND=cognito` のとき、`LEGACY_X_API_KEY` がローカル既定値のままだと起動を拒否します

## 旧データ移行

旧 4 テーブル（`thread` / `log` / `like` / `user`）から single-table へは `scripts/migrate_v2_import.py` を使います。再実行は upsert のため冪等です。

```bash
# 件数確認（書き込みなし）
uv run python scripts/migrate_v2_import.py --dry-run --source-profile algon2-prod

# 実行（nRes/nLike を再計算して差分レポート）
DDB_ENDPOINT_URL=http://localhost:8001 uv run python scripts/migrate_v2_import.py \
  --source-profile algon2-prod --recompute-counts
```

S3 資産はキー規約が同じなのでそのままミラーします。

```bash
aws s3 sync s3://img.algodooonline.net ./assets-dump
aws --endpoint-url http://127.0.0.1:9000 s3 sync ./assets-dump s3://algodoo-assets
```

## ローカル結合テスト

Docker Compose だけでアプリ、DynamoDB API mock、S3 API mock、結合テスト用コンテナを起動し、テスト終了コードを返します。移行スクリプトの結合テストも同じプロファイルで実行されます。

```bash
docker compose --profile test up --abort-on-container-exit --exit-code-from integration
```

短縮コマンド:

```bash
sh scripts/test-integration-local.sh
```

Cognito バックエンドの結合テスト（moto の cognito-idp を利用）:

```bash
docker compose --profile test-cognito up --abort-on-container-exit --exit-code-from integration-cognito
```

本番トポロジ（ビルド済みイメージ + DynamoDB Local + SeaweedFS S3、local 認証）の検証:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.ci up -d --build
BASE_URL=http://127.0.0.1:8080 ASSET_PUBLIC_BASE_URL=http://localhost:9000/algodoo-assets \
  S3_INTERNAL_BASE_URL=http://127.0.0.1:9000/algodoo-assets python3 scripts/integration_local.py
```

## Playwright e2e テスト（全画面のブラウザ結合テスト）

`scripts/integration_local.py` はHTTPレベルの結合テストですが、`tests/e2e` は実際の Chromium で SPEC.md の全画面（ホーム・Navbar・認証4画面・掲示板一覧/詳細・投稿/返信/編集/削除・Like・検索/並べ替え・IMAGE/DATA添付・Markdown サニタイズ）を操作して検証します。GitHub Actions でも同じプロファイルを実行します。

```bash
docker compose --profile e2e up --abort-on-container-exit --exit-code-from e2e
```

短縮コマンド:

```bash
sh scripts/test-e2e-local.sh
```

`app` コンテナに対して素の `uv run pytest` で直接実行したい場合（Playwright ブラウザは別途 `playwright install --with-deps chromium` が必要）:

```bash
uv sync --all-packages --group e2e
uv run --group e2e playwright install --with-deps chromium
BASE_URL=http://localhost:8080 uv run --group e2e pytest tests/e2e
```

実行後、`test-results/report.html` をブラウザで直接開くとテスト結果（成否・所要時間・失敗時のトレースバック）を一覧で確認できます（`docker compose --profile e2e` 実行時もリポジトリ直下にバインドマウントされるので、コンテナが終了した後にホスト側でそのまま開けます）。失敗したテストのスクリーンショット・動画・trace は同じ `test-results/<テスト名>/` 配下に出力され、trace は次のコマンドでブラウザ操作を録画のように再生しながら確認できます。

```bash
uv run --group e2e playwright show-trace test-results/<テスト名>/trace.zip
```

## 参照元

- APP: `../Algon2-APP`
- API: `../Algon2-API`
- DynamoDB ライブラリ: `https://github.com/medaka0213/DynamoDB-SingleTable`
