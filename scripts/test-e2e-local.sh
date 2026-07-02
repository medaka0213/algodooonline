#!/bin/sh
set -eu

docker compose --profile e2e up --abort-on-container-exit --exit-code-from e2e
