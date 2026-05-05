# algodooonline

2019 年の `../Algon2-APP` と `../Algon2-API` を、Python + `uv` 前提で統合した Algodoo Online のモノレポです。

旧仕様の受け入れ条件は [`SPEC.md`](SPEC.md) に固定しています。画面・認証・API・データ移行はこの仕様との差分がなくなるまで完了扱いにしません。

## 方針

- UI と API は `FastAPI + Jinja2` で統合し、Lambda 上で 1 アプリとして動かす
- 認証は Cognito を維持しつつ、フロント直書きのトークン管理からサーバー主導のセッション設計へ移す
- DynamoDB は維持し、物理テーブルは `ddb_single` を使った single-table 設計へ寄せる
- デプロイ先は AWS サーバーレス前提。従量課金で無料枠に収まりやすい構成を選ぶ

## 構成

- `apps/web`: 画面と API をまとめた新しい Python アプリ
- `packages/domain`: ドメインモデル
- `packages/data`: DynamoDB single-table モデルとデータ層
- `scripts`: ローカル起動と結合テスト

## 開始コマンド

```bash
uv sync --all-packages
uv run --package algodoo-web uvicorn algodoo_web.main:app --reload
```

## Docker Compose

```bash
docker compose up
```

- アプリ: `http://localhost:8080`
- DynamoDB API mock: `http://localhost:8001`
- S3 API mock: `http://localhost:8002`

初回起動時にアプリが DynamoDB single-table を自動作成し、デモ用の thread/log/like を投入します。
ローカル compose では DynamoDB と S3 の API 互換 `moto_server` を別コンテナとして立ち上げます。アプリ側のデータアクセスは `boto3 + ddb_single`、添付保存は `boto3` S3 client のままです。

## ローカル結合テスト

Docker Compose だけでアプリ、DynamoDB API mock、S3 API mock、結合テスト用コンテナを起動し、テスト終了コードを返します。

```bash
docker compose --profile test up --abort-on-container-exit --exit-code-from integration
```

短縮コマンド:

```bash
sh scripts/test-integration-local.sh
```

## 参照元

- APP: `../Algon2-APP`
- API: `../Algon2-API`
- DynamoDB ライブラリ: `https://github.com/medaka0213/DynamoDB-SingleTable`
