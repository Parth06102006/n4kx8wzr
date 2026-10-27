# Renewable Forecast

A full-stack dashboard for exploring UK wind power forecasts and generation outturns. The application uses a React/TypeScript frontend and a FastAPI backend, with PostgreSQL for application data and Elexon wind data in `data/elexon/`.

## Live application

Deployed on Vercel: [Renewable Forecast](https://renewable-forecast.vercel.app)

## Start locally

### Requirements

- [Docker](https://www.docker.com/)
- [uv](https://docs.astral.sh/uv/) for Python dependencies
- [Bun](https://bun.sh/) for frontend dependencies

From the repository root, install dependencies and start the development stack:

```bash
uv sync
bun install
bun run dev
```

The `dev` script starts PostgreSQL through Docker Compose, applies backend database setup, and launches the API and Vite development server. Open the frontend at <http://localhost:5173>. The API is at <http://localhost:8000>, with interactive API docs at <http://localhost:8000/docs>.

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
| `data/elexon/` | Elexon wind forecast and actual generation CSV data. |
| `scripts/` | Development, client generation, data import, and test helper scripts. |
| `scripts/tests/` | Tests for repository-level scripts. |
| `_reference/` | Project notes, design/reference documents, and deployment/development guides. |
| `compose.yml` | Docker Compose services shared by development and deployment. |
| `compose.override.yml` | Local Docker Compose development overrides. |
| `compose.deploy.yml` | Deployment-specific Docker Compose configuration. |
| `vercel.json` | Vercel frontend/backend service and routing configuration. |
| `pyproject.toml`, `uv.lock` | Python project configuration and locked dependencies. |
| `package.json`, `bun.lock` | Root Bun workspace scripts and locked JavaScript dependencies. |
| `LICENSE` | Project license. |

For more detailed setup, see [`_reference/development.md`](_reference/development.md). Backend and frontend notes are in [`backend/README.md`](backend/README.md) and [`frontend/README.md`](frontend/README.md).
