#! /usr/bin/env bash

set -e
set -x

cd backend
if command -v uv &> /dev/null; then
  PYTHON_CMD="uv run python"
elif [ -f "../.venv/bin/python" ]; then
  PYTHON_CMD="../.venv/bin/python"
else
  PYTHON_CMD="python3"
fi

FASTAPI_ENV=development $PYTHON_CMD -c "import app.main; import json; print(json.dumps(app.main.app.openapi()))" > ../openapi.json
cd ..
mv openapi.json frontend/
bun run --filter frontend generate-client
bun run lint
