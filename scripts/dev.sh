#!/usr/bin/env bash
set -e

# Always run from the repository root
cd "$(dirname "$0")/.."

echo "==> Ensuring PostgreSQL container is running..."
docker compose up -d db

echo "==> Waiting for PostgreSQL to be ready on port 5436..."
(cd backend && uv run python -c '
import time, sys
from sqlalchemy import create_engine, text
from app.core.config import settings

engine = create_engine(str(settings.DATABASE_URL))
start = time.time()
while time.time() - start < 45:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            print("==> Database is ready and accepting connections!")
            sys.exit(0)
    except Exception:
        time.sleep(1)
print("==> Timed out waiting for database. Check container logs with: docker compose logs db", file=sys.stderr)
sys.exit(1)
')

echo "==> Running database migrations and initialization..."
(cd backend && uv run bash scripts/prestart.sh)

# Gracefully shut down background child processes on exit
cleanup() {
    echo ""
    echo "==> Stopping development servers..."
    kill $(jobs -p) 2>/dev/null || true
    wait $(jobs -p) 2>/dev/null || true
    echo "==> Servers stopped."
}
trap cleanup SIGINT SIGTERM EXIT

echo "==> Starting Backend on http://localhost:8000 ..."
(cd backend && uv run fastapi dev) &

echo "==> Starting Frontend on http://localhost:5173 ..."
(cd frontend && bun run dev) &

# Wait for background jobs
wait
