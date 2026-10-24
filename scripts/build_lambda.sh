#!/bin/sh
# Build the AWS Lambda deployment zip (python3.12 / x86_64) into dist/lambda.zip.
# Usage: sh scripts/build_lambda.sh
set -eu

cd "$(dirname "$0")/.."

BUILD_DIR=dist/lambda
ZIP_PATH=dist/lambda.zip

# Empty the directory in place (not rm -rf): the test-lambda compose profile
# bind-mounts it into the Lambda runtime container.
mkdir -p "$BUILD_DIR"
find "$BUILD_DIR" -mindepth 1 -delete
rm -f "$ZIP_PATH"

# Third-party deps pinned by uv.lock (workspace members are installed below).
uv export --frozen --no-dev --all-packages --no-emit-workspace --no-hashes \
  -o dist/lambda-requirements.txt >/dev/null
uv pip install --quiet --target "$BUILD_DIR" \
  --python-version 3.12 --python-platform x86_64-manylinux2014 \
  --compile-bytecode -r dist/lambda-requirements.txt
uv pip install --quiet --target "$BUILD_DIR" --no-deps \
  --python-version 3.12 --python-platform x86_64-manylinux2014 \
  --compile-bytecode ./packages/domain ./packages/data ./apps/web

# setuptools leaves build/ trees inside the workspace members.
rm -rf apps/web/build packages/domain/build packages/data/build

# Not needed at runtime; keeps the zip under the 50 MB direct-upload limit.
rm -rf "$BUILD_DIR"/bin
find "$BUILD_DIR" -type d -name tests -prune -exec rm -rf {} +

(cd "$BUILD_DIR" && python3 -c "
import os, zipfile
with zipfile.ZipFile('../lambda.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
    for root, dirs, files in os.walk('.'):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(root, name)
            info = zipfile.ZipInfo(os.path.relpath(path, '.'), (1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(path, 'rb') as fh:
                zf.writestr(info, fh.read())
")
echo "built $ZIP_PATH ($(du -h "$ZIP_PATH" | cut -f1))"
