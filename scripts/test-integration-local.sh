#!/bin/sh
set -eu

docker compose --profile test up --abort-on-container-exit --exit-code-from integration
