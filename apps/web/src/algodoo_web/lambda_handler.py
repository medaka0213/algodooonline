"""AWS Lambda entry point (API Gateway HTTP API, payload format 2.0)."""

from mangum import Mangum

from algodoo_web.main import app

# lifespan="auto" runs the FastAPI startup (settings validation + table init)
# once per cold start, the same as uvicorn does per process.
handler = Mangum(app, lifespan="auto")
