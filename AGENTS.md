# AGENTS.md

## Project

This repository is the Python-first rewrite of the legacy Algon2 React + Chalice application.

The local app must behave like the target product, not like a migration status page. Keep user-facing screens focused on the actual Algodoo Online workflows: routes, thread lists, thread detail, responses, replies, likes, search, simple local session, and attachment references.

## Stack

- Python 3.12
- uv workspace
- FastAPI + Jinja2
- Mangum for Lambda compatibility
- boto3 + `ddb_single`
- Docker Compose for local integration testing
- Local DynamoDB API compatibility is provided by `moto_server` in the app container

## Commands

Run the local app:

```bash
docker compose up
```

Open:

```text
http://localhost:8080
```

Run the local integration smoke test:

```bash
docker compose exec app python /app/scripts/smoke_local.py
```

Syntax check without writing bytecode:

```bash
python3 -B -c "import ast, pathlib; [ast.parse(p.read_text()) for p in pathlib.Path('.').glob('**/*.py') if '.venv' not in p.parts and '__pycache__' not in p.parts and 'vendor' not in p.parts]; print('syntax ok')"
```

## Repository Layout

- `apps/web`: FastAPI app, HTML views, and JSON API routes
- `packages/domain`: domain dataclasses and enums
- `packages/data`: DynamoDB single-table models and repository functions
- `scripts`: local dev and smoke test scripts

## Development Rules

- Treat the Docker Compose app as the local integration target.
- Keep the main screen as a usable application screen.
- Do not add migration notes, schema descriptions, access pattern docs, or architecture explanations to the user-facing app UI.
- If a feature changes UI behavior, update `scripts/smoke_local.py` to cover the expected flow.
- Keep data access behind `packages/data/src/algodoo_data/repository.py`.
- Do not bypass `ddb_single` for normal DynamoDB model operations.
- Do not vendor or commit `DynamoDB-SingleTable`; keep it as the separate dependency declared in `packages/data/pyproject.toml`.
- Prefer server-rendered forms for core workflows until the app has a clear reason to add client-side JavaScript.
- Local session behavior is intentionally lightweight and Cookie-based; production Cognito integration should replace it without changing the repository interface.
