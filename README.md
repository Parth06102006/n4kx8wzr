# Renewable Forecast

A full-stack dashboard for exploring UK wind power forecasts and generation outturns. The application uses a React/TypeScript frontend and a FastAPI backend, with PostgreSQL for application data and Elexon wind data in `data/elexon/`.

## Live application

Deployed on Vercel: [Renewable Forecast](https://renewable-forecast.vercel.app)

## Start locally

### Requirements and configuration

- [Docker](https://www.docker.com/) with Docker Compose
- [uv](https://docs.astral.sh/uv/) for Python dependencies
- [Bun](https://bun.sh/) for frontend dependencies
- Python 3.12 or newer

Create a root `.env` file (it is intentionally Git-ignored) and set a local PostgreSQL password in `POSTGRES_PASSWORD`. Set `DATABASE_URL` to match the Compose database, for example:

```dotenv
FASTAPI_ENV=development
POSTGRES_PASSWORD=local-dev-password
DATABASE_URL=postgresql://postgres:local-dev-password@localhost:5436/app
```

Do not use these local credentials in a deployed environment. Compose publishes PostgreSQL on host port `5436`; the backend running on your machine connects through `localhost:5436`.

For the separate Vite development server, create `frontend/.env` with the local API URL:

```dotenv
VITE_API_URL=http://localhost:8000
```

### Fetch and prepare the Elexon data

The import script downloads wind actuals and forecasts from the Elexon BMRS API and writes normalized CSV files under the ignored `data/elexon/` directory. It can cache raw API responses and reuse them on later runs:

```bash
python3 scripts/elexon_history_import.py
```

Add `--refresh` to re-download cached source responses. The database initializer also runs this importer automatically if the expected normalized CSVs are missing, so this step can be skipped when using the combined development command below. The initial download requires network access to the Elexon API.

### Run database, backend, and frontend

From the repository root, install dependencies:

```bash
uv sync
bun install
```

**Recommended — start the complete local development setup:**

```bash
bun run dev
```

This runs `scripts/dev.sh`, which starts the PostgreSQL container, waits for it to become ready, applies Alembic migrations and initializes/validates the dataset through `backend/scripts/prestart.sh`, then starts both development servers. If the database is empty, initialization imports the CSV data (and fetches it first if it is missing). Press `Ctrl+C` to stop the servers. The database container remains running; stop it with `docker compose down` when finished.

**Or run each part in separate terminals:**

1. Start PostgreSQL from the project root:

   ```bash
   docker compose up -d db
   ```

2. Apply migrations and load/validate data:

   ```bash
   cd backend
   uv run bash scripts/prestart.sh
   ```

   `prestart.sh` upgrades the schema and runs `app/initial_data.py`. That initializer loads existing CSVs, or invokes the Elexon importer if the files are absent.

3. Start the backend in one terminal, from `backend/`:

   ```bash
   uv run fastapi dev
   ```

4. Start the frontend in another terminal, from the repository root:

   ```bash
   cd frontend
   bun run dev
   ```

Open the frontend at <http://localhost:5173>, the API at <http://localhost:8000>, and interactive API docs at <http://localhost:8000/docs>. The Vite frontend connects to the local FastAPI backend.

For a database/data status check, from `backend/` run `uv run python app/initial_data.py --check-only`. To force a data reload, run `uv run python app/initial_data.py --force` (with PostgreSQL running).

### Useful review commands

```bash
bun run lint
bun run test
cd backend && uv run bash scripts/test.sh
python -m pytest scripts/tests
```

For deployment details, see [`vercel.json`](vercel.json) and the Docker Compose configuration files.

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/` | FastAPI application, database models and migrations, API endpoints, services, and backend tests. |
| `backend/app/api/` | HTTP API routes. |
| `backend/app/core/` | Application configuration and shared backend infrastructure. |
| `backend/app/services/` | Backend service/business logic. |
| `backend/app/alembic/` | Alembic database migrations. |
| `frontend/` | Vite/React/TypeScript application, frontend tests, and static assets. |
| `frontend/src/` | Frontend source, including pages, routes, components, hooks, API client, and shared utilities. |
| `frontend/public/` | Static files served by the frontend. |
| `scripts/` | Development, client generation, data import, and test helper scripts. |
| `scripts/tests/` | Tests for repository-level scripts. |
| `compose.yml` | Docker Compose services shared by development and deployment. |
| `compose.override.yml` | Local Docker Compose development overrides. |
| `compose.deploy.yml` | Deployment-specific Docker Compose configuration. |
| `vercel.json` | Vercel frontend/backend service and routing configuration. |
| `pyproject.toml`, `uv.lock` | Python project configuration and locked dependencies. |
| `package.json`, `bun.lock` | Root Bun workspace scripts and locked JavaScript dependencies. |
| `LICENSE` | Project license. |

See [`architecture.md`](architecture.md) for the system diagrams, architecture, and data flow. Backend and frontend notes are in [`backend/README.md`](backend/README.md) and [`frontend/README.md`](frontend/README.md).
